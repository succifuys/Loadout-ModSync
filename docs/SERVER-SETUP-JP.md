# Loadout ModSync：サーバー設定の詳しい手順

[日本語 README に戻る](../readmeJP.md) · [Русская версия](SERVER-SETUP.md)

### どこに何を入れるか

| 場所 | 入れるもの |
| --- | --- |
| ゲームサーバー | 対応する Docker イメージの中で、公式の Dedicated Server と普段使っている SteamCMD／WorkshopManager を動かします。 |
| 同じホスト | 別の Docker Compose プロジェクトとして配布用の Mod Sync API を入れます。ゲームの状態を見る `dntsne-monitor` は systemd のサービスとして動かします。 |
| プレイヤーの PC | Windows ランチャーだけです。プレイヤー側に Dedicated Server や SteamCMD は不要です。 |

この例は **Linux、Docker Compose、systemd** 向けです。PZ のイメージには `/scripts/config/main.py`、WorkshopManager、元の `/scripts/init-server.sh` が必要です。既存の Compose をそのまま置き換えるものではありません。別のイメージ、Docker を使わないサーバー、Windows の Dedicated Server では、先にテスト環境で調整してください。

### 1. テスト環境を用意する

- プレイヤーに知らせ、管理用の RCON で `save`、次に `quit` を実行し、ゲームサーバーが止まるまで待ちます。停止後に**ワールド、サーバーの INI、Compose の設定**をバックアップします。保存中のコンテナを強制終了しないでください。
- 最初は別のコンテナとワールドのコピーを使います。同じセーブ先を 2 台のサーバーで同時に使わないでください。
- 設定例では `/srv/servers/pz` がゲームの作業場所で、`data` にワールドや設定、`workshop` に Workshop のファイルがあります。Mod Sync 本体は `/opt/dntsne-modsync` に入ります。自分の構成に合わせて、関係する設定のパスをそろえてください。
- `dntsne/host_monitor.py` と `deploy/dntsne-monitor.service` を確認します。標準のコンテナ名は `pz-server`、監視するゲームのポートは `16261`、読み込む INI は `data/Server/DNTSNE.ini` です。ポートや INI 名が違う場合は監視側も調整が必要です。ルートとコンテナ名は `--root` と `--container` で指定できます。

### 2. 監視サービスと配布用 API を入れる

`deploy/compose.modsync.yaml` のアドレスとパスを自分のものに直します。初期設定では `8787/tcp` は `127.0.0.1` にだけ開きます。プレイヤー向けに公開するときは、下の例に沿って `DNTSNE_BIND_IP` に自分の Tailscale IP を指定します。インターネットには公開しないでください。ゲーム用ポートと API 用ポートは別です。同期のために RCON を外に公開する必要はありません。

初回は設定とパスを確認してから、ソースのルートで実行します。

```bash
sudo sh scripts/install-server.sh --approved
```

`/opt/dntsne-modsync` にファイルをコピーし、監視サービスと API を起動します。PZ の INI は書き換えず、PZ も再起動しません。すでにインストールされていればスクリプトは止まります。アップデート時は消して入れ直す前に、現在の設定を保存して差分を確認してください。

### 3. PZ がローカルの MOD を読むようにする

1. `deploy/compose.pz.override.example.yaml` をコピーして、既存の Compose に追加する設定を作ります。先に `workshop/.dntsne-local-mods` を作り、ゲームに読み込み専用で割り当てます。元の Workshop ファイルと同じデータを参照する仕組みなので、両方を同じファイルシステムに置きます。
2. 使用する Docker イメージと同じ版から、元の `/scripts/init-server.sh` を取り出して保存します。Java エージェント用の例を使う場合は、ソースのルートで下のコマンドを実行し、別ファイルとして作ります。

```bash
python3 deploy/patch-pz-init.py /path/to/original-init-server.sh /path/to/dntsne-init.sh
```

   認識できないというエラーが出たら、無理に通さず、イメージに合わせて設定を見直します。例には ZombieBuddy 用の設定があります。使う場合だけ正しい JAR の場所を指定してください。使わない場合は `DNTSNE_JAVA_AGENT` の例を外し、テストサーバーの起動を確認します。ゲーム本体の JAR は置き換えません。

3. SteamCMD に必要なため、起動設定の `WORKSHOP_ITEMS` には数値の Workshop ID を残します。`MODS` には Mod ID、`MAP` にはマップの設定を入れます。別々の値です。一方、準備後の**ゲーム側の INI** では `WorkshopItems=` が空であることを確認します。こうすると接続時に Workshop から別の版を取るように求められず、ローカルの MOD を使えます。`Mods=` と `Map=` も確認します。
4. 起動前に Compose の設定を確認します。ファイル名は自分の環境に合わせてください。

```bash
docker compose -f compose.yaml -f compose.modsync.override.yaml config --quiet
```

   Linux でマウントする `pz-entrypoint.sh` と `dntsne-init.sh` に実行権限があるか確認してから、テスト用 PZ を同じ Compose 設定で起動し、必要な MOD とマップが読み込まれるか確認します。API のインストーラーだけでは PZ 側の設定は変わりません。

### 4. 配布を有効にする

配布を始める前に、使う MOD **すべて**の配布条件を確認します。閉じたネットワークでも作者の条件は変わりません。配布できることを確認したら、`/opt/dntsne-modsync/.env` に `DNTSNE_LICENSES_APPROVED=1` と書き、`DNTSNE_BIND_IP` には自分の Tailscale IP を指定します。その後、次のコマンドで読み込ませます。

```bash
sudo chmod 600 /opt/dntsne-modsync/.env
sudo docker compose --env-file /opt/dntsne-modsync/.env \
  -f /opt/dntsne-modsync/deploy/compose.modsync.yaml up -d --build
```

ファイルが正しいかのチェックと、誰に配布するかの管理は別です。ほかの PC からは、許可した人だけが API にアクセスできるようにします。Workshop のファイル、ワールド、実際の設定、トークン、パスワードを公開リポジトリや Releases に入れないでください。

### 5. プレイヤー側まで確認する

同じネットワークにいる別の PC から、`pz-host` を自分のアドレスに変えて確認します。

```bash
curl -fsS http://pz-host:8787/api/v1/status
```

`"state":"ready"`、PZ のバージョン、`revision` が返れば、配布の準備ができています。応答はあるのに準備ができない場合はログを見ます。

```bash
sudo journalctl -u dntsne-monitor -n 80 --no-pager
sudo docker compose --env-file /opt/dntsne-modsync/.env \
  -f /opt/dntsne-modsync/deploy/compose.modsync.yaml logs --tail=80 modsync
```

1. 空のプロファイルで初回の同期をして、テストワールドに入ります。
2. 何も変更せず、もう一度 **Synchronize** を押します。ここではファイルを取り直さないことを確認します。
3. テストサーバーで MOD を 1 つ更新し、PZ を通常の手順で再起動します。`ready` を待ってから、プレイヤー側で実際にダウンロードされた量を確認します。
4. 更新後もゲームに入れることを確認します。動かない場合は本番に反映しません。元に戻すときは Compose、スクリプト、INI のバックアップを使い、最新のセーブを古いワールドで上書きしないようにします。

### MOD の更新手順

SteamCMD は PZ が起動する準備のときに Workshop の MOD を更新します。**PZ の動作中に Workshop フォルダーを手作業で更新しないでください。** ローカルの MOD と Workshop が同じファイルのデータを使うためです。ゲームサーバーを通常の手順で止め、次の起動で更新し、API が `ready` になるまで待ちます。それからプレイヤーに **Synchronize** を押してもらいます。

更新のためのゲームサーバー再起動は必要です。このツールで減らすのは、プレイヤーが何度も入り直したり、パック全体を取り直したりする手間です。サーバーを再起動して `revision` が変わっても、内容が同じファイルは再ダウンロードしません。

0.1.3 では、実際の MOD パックで、変更がない状態での再同期を確認しました。同じプロファイルでの初回同期には 0.1.2 を使いました。1 ファイルだけ変えた場合はテスト用のデータで確認しています。実際に Workshop の MOD を一つ更新してからゲームに入り直すところまでは、テストサーバーで別途確認が必要です。


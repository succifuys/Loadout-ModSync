# Loadout ModSync

[English](README.md) · [ロシア語版](ReadMe-RU.md)

BY CHAT**JP**T IM SORRY

Loadout ModSync は、**Project Zomboid Dedicated Server** 用の Windows ランチャーと、MOD を配るためのサーバー側ツールです。鯖は今までどおり SteamCMD で Workshop から MOD を取ってきます。プレイヤーに渡すのは、**今その鯖で動いている版**。さっき Workshop に来た最新版とは限りません。

作者がアプデした。でも鯖はまだ再起動してない。そんなときに「MOD 外して、入れ直して、もう一回入り直して」をやらなくて済むように作りました。**初回だけは一式ダウンロードします。** その後は足りないファイルと変わったファイルだけ。1 ファイル変わったくらいで、MOD パックごとおかわりしなくていいです。

以下は **0.1.3** の説明です。クライアントは Windows、鯖は **Build 42.22.2** で確認しました。別のバージョンや Docker イメージでも動くか？ そこはまだ約束できません。

## 鯖民のみなさんへ（プレイヤー向け）

必要なのは Steam 版 Project Zomboid、鯖と同じゲームのバージョン、Windows x64、そして管理人からもらった **ModSync の URL**。ゲームに入るためのアドレスとポートは別です。とりあえず両方に同じものを入れるのはナシで。

1. Windows x64 用のビルドを管理人からもらうか、**Releases** にあればそこから取ってきます。遊ぶだけならソースコードはいりません。
2. 単体版の `Loadout-ModSync.exe` ならそのまま起動。フォルダー版なら ZIP を**丸ごと**展開します。置き場所は `C:\Games\LoadoutModSync` などでOK。`DNTSNE-ModSync.exe` を起動します。EXE の名前はまだ旧名です。`_internal` は隣に置いたまま。EXE だけ連れていくと起きません。Python は別に入れなくて大丈夫です。
3. Steam を起動します。管理人の Tailscale ネットワークにつなぎます。この版は通常の公開 IP や Radmin VPN のアドレスでは同期できません。**同期する前に PZ は閉じてください。**
4. **Settings** の **Tailscale server URL** に、管理人からもらった URL を入れます。たとえば `http://100.64.0.1:8787`。IP は実際の Tailscale IP に替えてね。ゲームが見つからないときは **Game folder** を指定します。Steam の **プロパティ → インストール済みファイル → 参照** から開いて、エクスプローラーのアドレスをコピペ。ここまで来た君ならいける。設定済みの ZIP なら、URL とゲームの場所だけ確認すればOKです。
5. **Mod folder** は基本そのまま。初期設定は `%LOCALAPPDATA%\DNTSNE\ModSync\game-profile\mods` です。**Workshop フォルダーは指定しないでね。ここだけはマジで。** 最後に **Save**。
6. **Synchronize** を押して、準備が終わるまで待ちます。初回はちょっと長いので、お茶でもどうぞ。空き容量は **MOD パックのサイズより多めに**。途中のファイルにも置き場所が要ります。
7. **Launch Project Zomboid** から起動します。この MOD パックで遊ぶときは **Steam の「プレイ」ではなく、ランチャーから**。ゲームのメニューで、管理人から聞いたアドレスとポートに接続します。

Workshop の登録と PZ 本体は変更しません。バニラや普段の Workshop MOD で遊ぶときは、いつもどおり Steam から起動してOK。ランチャーを二つ開いて同時に同期するのはやめてください。分身の術じゃなくて、同じフォルダーの取り合いになります。

### 動かん。どうする？

- **ゲームのバージョンが違う。** 管理人とビルド番号・ブランチを確認して、Steam で合わせます。ModSync はゲーム本体を更新しません。
- **鯖が応答しない、または更新中。** URL とネットワークを確認。ほかの人も入れないなら、まず鯖管に聞きましょう。こっちだけ再インストールするガチャは回さなくていいです。
- **同期したのに MOD エラー。** ゲームを閉じて **Settings → Full verification (reads every file)** を試します。いきなり MOD フォルダーを全消ししないでください。入れ直すなら、自分で足したファイルを先に退避。
- **エラーの意味が分からない。** **Open log file** からエラーの前後を数行、鯖管に送ります。「動かん」だけだと、さすがの鯖管もエスパーじゃないです。ChatGPT や Claude に聞くときも、パスワード、トークン、非公開のアドレスは消してください。

## 鯖缶のみなさんへ（管理者向け）

| どこ | 何を動かす？ |
| --- | --- |
| **HOST** | 対応する Docker イメージで公式 Dedicated Server を動かします。SteamCMD と WorkshopManager は今までどおり。 |
| **HOST** | 別の Compose プロジェクトで ModSync API、systemd で `dntsne-monitor`。前者は配る係、後者は今動いている鯖を見る係です。 |
| **CLIENT** | ランチャー。ここで SteamCMD まで入れ始めなくて大丈夫です。 |

### サーバーへの入れ方

**Linux、Docker Compose、systemd で PZ サーバーをすでに動かしている場合**は、次の手順で試せます。この例は WorkshopManager と `/scripts/config/main.py`、`/scripts/init-server.sh` があるイメージ向けです。別のイメージや Windows Dedicated Server 向けの自動インストーラーはまだありません。

1. **ワールド、INI、Compose の設定をバックアップします。** 最初は本番ではなく、別のコンテナとワールドのコピーで試します。
2. **MOD 配布用のサービスを入れます。** ソースの `deploy/compose.modsync.yaml` を開き、パスとアドレスを自分の環境に合わせます。初回はホスト内からしかアクセスできません。あとで配布を有効にするときに Tailscale IP を指定します。ソースのルートで次を実行します。

   ```bash
   sudo sh scripts/install-server.sh --approved
   ```

   監視サービスと API が入ります。**PZ 本体の設定や再起動は、このスクリプトでは行いません。**
3. **ゲームサーバーがローカルの MOD を読むようにします。** `deploy/compose.pz.override.example.yaml` のパスを調整し、テスト用の Compose に追加します。起動設定の `WORKSHOP_ITEMS` は SteamCMD 用に残します。起動後の INI では `WorkshopItems=` が空で、`Mods=` と `Map=` は必要な値のままか確認します。[パスの例と起動ファイルの準備](docs/SERVER-SETUP-JP.md)も参照してください。
4. **配布を有効にして確認します。** MOD の配布条件を確認したら、[手順](docs/SERVER-SETUP-JP.md)に沿って `DNTSNE_LICENSES_APPROVED=1` を設定します。同じネットワークの別の PC から `http://TAILSCALE-IP:8787/api/v1/status` を開き、`"state":"ready"` が返ったら、プレイヤーに `http://TAILSCALE-IP:8787` を伝えます。ゲームの接続先は別に伝えてください。

**MOD を更新するとき：** PZ を通常の手順で再起動し、`ready` を待ってからプレイヤーに **Synchronize** を押してもらいます。PZ の動作中は、Workshop フォルダーを手作業で更新しないでください。

[管理者向けの詳しい手順：パス、コマンド、起動しないときの確認先](docs/SERVER-SETUP-JP.md)

## 開発と今後の予定

Windows の PowerShell で、ソースのルートからクライアントを起動する例です。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-client.lock
.\.venv\Scripts\python.exe client_app.py
```

Python **3.12 以上**が必要です。lock ファイルの依存パッケージが入るバージョンを使ってください。テストする場合は `requirements-server.lock` の依存パッケージと `pytest httpx` も入れて、`.\.venv\Scripts\python.exe -m pytest` を実行します。配布用の Windows ビルドは `scripts/build-client.ps1` で作ります。出力先は `dist/0.1.3/DNTSNE-ModSync` です。EXE だけでなく `_internal` を含むフォルダー全体を配布します。単体 EXE が欲しい場合は `.\scripts\build-exe.ps1` を実行します。出力は `dist/Loadout-ModSync.exe`。[ビルドと ZIP の作り方（英語）](docs/BUILD.md)。

- [ファイルの確認とダウンロードの仕組み（英語）](docs/PROTOCOL.md)
- [0.1.3 の変更点（英語）](docs/RELEASE-0.1.3.md)
- [依存パッケージと配布について（英語）](docs/LICENSES.md)

**今後の予定：** ゲームサーバーとは別のホストから MOD を配れるようにします。現在は PZ と同じホストで API を動かし、準備済みの MOD を読み込む構成です。別ホストでの配布はまだ対応していません。

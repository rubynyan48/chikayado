# ちか宿（ちか宿.jp）

イベント会場の近くの宿を、会場からの距離順とイベント開催日の空室で案内するサイト。
GitHub Actions が毎日自動でデータを取り直し、ページを作ってXサーバーへ転送する。

## 毎日の自動更新（日本時間 5:17）

1. 東京都オープンデータのCSVからイベントを取得し、`data/events/` に貯める（過去分は消さない）
2. 楽天トラベルAPIで会場から3km以内の宿を取得（`data/hotels/`）
3. これから開催されるイベントごとに、初日の空室と最安料金を取得（`data/vacancy/`）
4. ホットペッパーAPIで、会場に近い宿の周りの飲食店を取得（`data/restaurants/`、キーがある場合）
5. 新しいイベントだけ、Gemini APIで短い解説文を書く（`data/texts/`、1イベント1回）
6. 取得データをリポジトリに保存し、`scripts/build.py` でページを生成して rsync で転送

手動で今すぐ動かすときは、Actions タブの「サイト更新」→「Run workflow」。
`templates/` や `static/` などを変えて push したときは、データは取り直さずにページの生成と転送だけ行う。

## 使うSecrets

| 名前 | 中身 |
|---|---|
| XSERVER_HOST / XSERVER_USER / XSERVER_PORT / XSERVER_SSH_KEY / XSERVER_PATH | Xサーバーへの転送 |
| RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY | 楽天トラベルAPI |
| HOTPEPPER_API_KEY | ホットペッパーグルメAPI（任意） |
| GEMINI_API_KEY | 解説文の生成（任意） |

転送先が `.../xn--u8j0b149r.jp/public_html` 以外になっていると、ほかのサイトを消さないよう転送を止める。

## あとから設定するもの（config/site.json）

- `rakuten_affiliate_id` 楽天アフィリエイトID。入れると次回の更新から予約リンクがアフィリエイトURLになる
- `ga_id` GA4の測定ID
- `operator` 運営者名と連絡先

## 写真

`static/images/` に次の名前で置くと、決まった場所に表示される。置いていない場所には何も出ない。

| ファイル名 | ページ |
|---|---|
| 東京ビッグサイト駅の改札.jpg / 東京ビッグサイト駅から見た会議棟.jpg / 東京ビッグサイト会議棟の前.jpg | ゆりかもめからの道順 |
| 国際展示場駅の改札.jpg / 国際展示場駅の出口.jpg / 国際展示場駅から会場への道のローソン.jpg / 東京ベイ有明ワシントンホテル前の道.jpg / 東京ビッグサイトの正面.jpg | りんかい線からの道順 |
| 東京ビッグサイト東展示棟のガレリア.jpg / 東京ビッグサイト西展示棟のアトリウム.jpg / 東京ビッグサイト南展示棟の入口.jpg / 東京ビッグサイト会議棟の外観.jpg | 展示棟の違い |
| 有明のホテル街.jpg | 泊まるエリアの選び方 |

Search Console の確認用HTMLファイルは `static/` の直下に置けば、サイトの一番上に公開される。

## 会場を増やす

`config/venues/` に会場のJSONを足す。イベントのCSVがない会場は `events_csv` を空にする。

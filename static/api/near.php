<?php
// トップの「イベント名・アーティスト名・会場名で探す」で、まだ載っていない会場や場所を入れられたときに、
// その場所の近くで空いている宿を楽天トラベルから出す（11/23〜）。入力された語句は次に足す会場の参考に記録する。
// 楽天のキーは公開フォルダの外（chikayado_private/config.php）に置き、ここには書かない。
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function fail($msg, $code = 400) {
    http_response_code($code);
    echo json_encode(['error' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

$private = dirname(__DIR__, 2) . '/chikayado_private';
$q = trim(mb_substr((string)($_GET['q'] ?? ''), 0, 60));
$q = preg_replace('/[\x00-\x1F\x7F]/u', '', $q);
if ($q === '') fail('探したい場所を入れてください。');

// 入力の記録（日時・語句・サイト内で見つかった件数）。毎朝の更新で取り寄せて、次に足す会場を決める
$hits = (int)($_GET['hits'] ?? -1);
if (is_dir($private)) {
    @file_put_contents("$private/queries.tsv", date('Y-m-d H:i') . "\t" . str_replace("\t", ' ', $q) . "\t$hits\n", FILE_APPEND | LOCK_EX);
}
if (($_GET['mode'] ?? '') === 'log') { echo '{"ok":true}'; exit; }

$conf = @include $private . '/config.php';
if (!is_array($conf) || empty($conf['app_id']) || empty($conf['access_key'])) {
    fail('空室検索の準備ができていません。しばらくしてからもう一度お試しください。', 503);
}

$date = $_GET['date'] ?? '';
$adults = (int)($_GET['adults'] ?? 1);
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) fail('日付の形式が正しくありません。');
$tz = new DateTimeZone('Asia/Tokyo');
$d = DateTime::createFromFormat('Y-m-d', $date, $tz);
$today = new DateTime('today', $tz);
if (!$d || $d < $today) fail('今日以降の日付を選んでください。');
if ($d > (clone $today)->modify('+330 days')) fail('約1年先までの日付を選んでください。');
if ($adults < 1 || $adults > 4) fail('人数は1人から4人までで選んでください。');

function get($url, $headers = []) {
    $ch = curl_init($url);
    curl_setopt_array($ch, [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15, CURLOPT_HTTPHEADER => $headers]);
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    return [$status, $body];
}

$cacheDir = $private . '/cache';
if (!is_dir($cacheDir)) @mkdir($cacheDir, 0700, true);
$cacheFile = "$cacheDir/near-" . md5("$q|$date|$adults") . '.json';
if (is_file($cacheFile) && time() - filemtime($cacheFile) < 1200) { readfile($cacheFile); exit; }

// 国土地理院の住所・地名検索で場所を緯度経度にする（施設名・駅名・住所が使える）
[$st, $body] = get('https://msearch.gsi.go.jp/address-search/AddressSearch?q=' . rawurlencode($q));
$geo = json_decode((string)$body, true);
if ($st != 200 || empty($geo[0]['geometry']['coordinates'])) {
    fail('「' . $q . '」の場所が見つかりませんでした。会場名のほか、駅名や住所でも探せます。', 404);
}
[$lng, $lat] = $geo[0]['geometry']['coordinates'];
$place = $geo[0]['properties']['title'] ?? $q;

// 楽天への問い合わせは1秒に1回までに抑える（search.php と同じ鍵を使う）
$lock = fopen("$cacheDir/lock", 'c');
flock($lock, LOCK_EX);
$last = (float)@file_get_contents("$cacheDir/last");
$wait = 1.1 - (microtime(true) - $last);
if ($wait > 0) usleep((int)($wait * 1000000));
$checkout = (clone $d)->modify('+1 day')->format('Y-m-d');
$query = http_build_query([
    'applicationId' => $conf['app_id'], 'accessKey' => $conf['access_key'], 'format' => 'json', 'formatVersion' => 2,
    'latitude' => $lat, 'longitude' => $lng, 'datumType' => 1, 'searchRadius' => 3,
    'checkinDate' => $date, 'checkoutDate' => $checkout, 'adultNum' => $adults, 'roomNum' => 1,
    'hits' => 30, 'sort' => '+roomCharge', 'responseType' => 'middle',
]);
[$st, $body] = get('https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426?' . $query,
                   ['Referer: https://xn--u8j0b149r.jp/', 'Origin: https://xn--u8j0b149r.jp']);
file_put_contents("$cacheDir/last", (string)microtime(true));
flock($lock, LOCK_UN);
if ($st == 404) { $json = ['hotels' => []]; }
elseif ($st != 200 || !$body) fail('楽天トラベルにつながりませんでした。少し待ってからもう一度お試しください。', 502);
else $json = json_decode($body, true);

// 宿ごとに、基本情報と、いちばん安いプランを集める
function collect($x, &$info, &$plans, $cur = []) {
    if (!is_array($x)) return;
    if (isset($x['hotelBasicInfo'])) $info = $x['hotelBasicInfo'];
    if (isset($x['roomBasicInfo'])) $cur = array_merge($cur, $x['roomBasicInfo']);
    if (isset($x['dailyCharge'])) { $c = array_merge($cur, $x['dailyCharge']); if (!empty($c['total'])) $plans[] = $c; return; }
    foreach ($x as $k => $v) {
        if ($k === 'hotelBasicInfo' || $k === 'roomBasicInfo') continue;
        if (is_array($v) && isset($v['roomBasicInfo']) && !isset($v['dailyCharge'])) { collect($v, $info, $plans, array_merge($cur, $v['roomBasicInfo'])); continue; }
        collect($v, $info, $plans, $cur);
    }
}
function dist($la1, $lo1, $la2, $lo2) {
    $r = 6371000; $p1 = deg2rad($la1); $p2 = deg2rad($la2);
    $a = sin(($p2 - $p1) / 2) ** 2 + cos($p1) * cos($p2) * sin(deg2rad($lo2 - $lo1) / 2) ** 2;
    return (int)round(2 * $r * asin(sqrt($a)));
}

// もしもの設定は、会場ごとの宿の一覧（hotels-*.json）に入っているものを使う
$any = glob(__DIR__ . '/hotels-*.json');
$m = $any ? (json_decode(file_get_contents($any[0]), true)['moshimo'] ?? null) : null;
$out_d = (clone $d)->modify('+1 day');
$out = [];
foreach ($json['hotels'] ?? [] as $entry) {
    $info = null; $plans = [];
    collect($entry, $info, $plans);
    if (!$info || !$plans) continue;
    usort($plans, fn($a, $b) => $a['total'] <=> $b['total']);
    $no = $info['hotelNo'];
    $url = "https://hotel.travel.rakuten.co.jp/hotelinfo/plan/{$no}?f_nen1=" . $d->format('Y') . "&f_tuki1=" . $d->format('n') . "&f_hi1=" . $d->format('j')
         . "&f_nen2=" . $out_d->format('Y') . "&f_tuki2=" . $out_d->format('n') . "&f_hi2=" . $out_d->format('j')
         . "&f_heya_su=1&f_otona_su={$adults}&f_s1=0&f_s2=0&f_y1=0&f_y2=0&f_y3=0&f_y4=0";
    if ($m) $url = "https://af.moshimo.com/af/c/click?a_id={$m['a_id']}&p_id={$m['p_id']}&pc_id={$m['pc_id']}&pl_id={$m['pl_id']}&url=" . rawurlencode($url);
    $dm = dist($lat, $lng, $info['latitude'] ?? $lat, $info['longitude'] ?? $lng);
    $out[] = [
        'name' => $info['hotelName'], 'walk' => (int)ceil($dm * 1.25 / 80), 'distance' => $dm >= 1000 ? sprintf('%.1fkm', $dm / 1000) : "{$dm}m",
        'distance_m' => $dm, 'image' => $info['hotelThumbnailUrl'] ?? '', 'rate' => $info['reviewAverage'] ?? null, 'bath' => false,
        'per_person' => (int)round($plans[0]['total'] / $adults), 'url' => $url,
    ];
}
usort($out, fn($a, $b) => $a['distance_m'] <=> $b['distance_m']);
$result = json_encode(['place' => $place, 'date' => $date, 'adults' => $adults, 'hotels' => array_slice($out, 0, 10)], JSON_UNESCAPED_UNICODE);
file_put_contents($cacheFile, $result);
echo $result;

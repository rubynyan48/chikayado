<?php
// 日付と人数を受け取り、会場の周りで空室のある宿を近い順に返す。
// 楽天のキーは公開フォルダの外（chikayado_private/config.php）に置き、ここには書かない。
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');

function fail($msg, $code = 400) {
    http_response_code($code);
    echo json_encode(['error' => $msg], JSON_UNESCAPED_UNICODE);
    exit;
}

$private = dirname(__DIR__, 2) . '/chikayado_private';
$conf = @include $private . '/config.php';
if (!is_array($conf) || empty($conf['app_id']) || empty($conf['access_key'])) {
    fail('空室検索の準備ができていません。しばらくしてからもう一度お試しください。', 503);
}

$venue = preg_replace('/[^a-z0-9-]/', '', $_GET['venue'] ?? '');
$date = $_GET['date'] ?? '';
$adults = (int)($_GET['adults'] ?? 1);
if (!preg_match('/^\d{4}-\d{2}-\d{2}$/', $date)) fail('日付の形式が正しくありません。');
$d = DateTime::createFromFormat('Y-m-d', $date, new DateTimeZone('Asia/Tokyo'));
$today = new DateTime('today', new DateTimeZone('Asia/Tokyo'));
if (!$d || $d < $today) fail('今日以降の日付を選んでください。');
if ($d > (clone $today)->modify('+330 days')) fail('約1年先までの日付を選んでください。');
if ($adults < 1 || $adults > 4) fail('人数は1人から4人までで選んでください。');

$hotelsFile = __DIR__ . "/hotels-$venue.json";
if (!$venue || !is_file($hotelsFile)) fail('会場が見つかりません。', 404);
$meta = json_decode(file_get_contents($hotelsFile), true);

// 同じ条件は20分間使い回す（楽天への問い合わせを減らすため）
$cacheDir = $private . '/cache';
if (!is_dir($cacheDir)) @mkdir($cacheDir, 0700, true);
$key = md5("$venue|$date|$adults");
$cacheFile = "$cacheDir/$key.json";
if (is_file($cacheFile) && time() - filemtime($cacheFile) < 1200) {
    echo file_get_contents($cacheFile);
    exit;
}

// 楽天への問い合わせは1秒に1回までに抑える
$lock = fopen("$cacheDir/lock", 'c');
flock($lock, LOCK_EX);
$last = (float)@file_get_contents("$cacheDir/last");
$wait = 1.1 - (microtime(true) - $last);
if ($wait > 0) usleep((int)($wait * 1000000));

$checkout = (clone $d)->modify('+1 day')->format('Y-m-d');
$offers = [];
for ($page = 1; $page <= 2; $page++) {
    $q = http_build_query([
        'applicationId' => $conf['app_id'], 'accessKey' => $conf['access_key'], 'format' => 'json', 'formatVersion' => 2,
        'latitude' => $meta['lat'], 'longitude' => $meta['lng'], 'datumType' => 1, 'searchRadius' => 3,
        'checkinDate' => $date, 'checkoutDate' => $checkout, 'adultNum' => $adults, 'roomNum' => 1,
        'hits' => 30, 'page' => $page, 'sort' => '+roomCharge', 'responseType' => 'small',
    ]);
    $ch = curl_init('https://openapi.rakuten.co.jp/engine/api/Travel/VacantHotelSearch/20170426?' . $q);
    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 15,
        CURLOPT_HTTPHEADER => ['Referer: https://xn--u8j0b149r.jp/', 'Origin: https://xn--u8j0b149r.jp'],
    ]);
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    file_put_contents("$cacheDir/last", (string)microtime(true));
    if ($status == 404) break;  // 空室なし
    if ($status != 200 || !$body) {
        flock($lock, LOCK_UN);
        fail('楽天トラベルにつながりませんでした。少し待ってからもう一度お試しください。', 502);
    }
    $json = json_decode($body, true);
    foreach ($json['hotels'] ?? [] as $entry) {
        $no = null; $plans = [];
        walk($entry, [], $no, $plans);
        if (!$no || !$plans) continue;
        usort($plans, fn($a, $b) => $a['total'] <=> $b['total']);
        $offers[(string)$no] = $plans[0];
    }
    if ($page >= (int)($json['pagingInfo']['pageCount'] ?? 1)) break;
    usleep(1100000);
}
flock($lock, LOCK_UN);

// 入れ子をたどって、宿の番号と、プランごとの料金を集める
function walk($x, $cur, &$no, &$plans) {
    if (!is_array($x)) return;
    if (isset($x['hotelNo']) && !$no) $no = $x['hotelNo'];
    if (isset($x['roomBasicInfo'])) $cur = array_merge($cur, $x['roomBasicInfo']);
    if (isset($x['dailyCharge'])) {
        $c = array_merge($cur, $x['dailyCharge']);
        if (!empty($c['total'])) $plans[] = $c;
        return;
    }
    $isList = array_keys($x) === range(0, count($x) - 1);
    foreach ($x as $v) {
        if ($isList && is_array($v) && isset($v['roomBasicInfo'])) { $cur = array_merge($cur, $v['roomBasicInfo']); continue; }
        walk($v, $cur, $no, $plans);
    }
}

$m = $meta['moshimo'] ?? null;
$out = [];
foreach ($meta['hotels'] as $h) {
    $o = $offers[$h['hotelNo']] ?? null;
    if (!$o) continue;
    $url = "https://travel.rakuten.co.jp/HOTEL/{$h['hotelNo']}/{$h['hotelNo']}.html";
    if ($m) {
        $url = "https://af.moshimo.com/af/c/click?a_id={$m['a_id']}&p_id={$m['p_id']}&pc_id={$m['pc_id']}&pl_id={$m['pl_id']}&url=" . rawurlencode($url);
    }
    $out[] = [
        'name' => $h['name'], 'walk' => $h['walk'], 'distance' => $h['distance'], 'image' => $h['image'],
        'rate' => $h['rate'], 'bath' => $h['bath'],
        'per_person' => (int)round($o['total'] / $adults), 'room' => $o['roomName'] ?? '', 'url' => $url,
    ];
}
$result = json_encode(['date' => $date, 'adults' => $adults, 'hotels' => $out], JSON_UNESCAPED_UNICODE);
file_put_contents($cacheFile, $result);
echo $result;

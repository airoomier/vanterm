<?php
/**
 * Vanterm form işleyici (WPForms yerine).
 * Formlar JS ile buraya POST edilir; JSON döner. JS kapalıysa geri yönlendirir.
 * Alan etiketleri form-ayarlar.php içinde (build sırasında sayfalardaki formlardan üretilir).
 */
declare(strict_types=1);

// PHP 7.4 uyumluluğu
if (!function_exists('str_contains')) { function str_contains($h, $n) { return $n === '' || strpos($h, $n) !== false; } }
if (!function_exists('str_starts_with')) { function str_starts_with($h, $n) { return strncmp($h, $n, strlen($n)) === 0; } }

const ALICI    = 'bilgi@vanterm.com';
const GONDEREN = 'form@vanterm.com';
const SITE     = 'Vanterm';

$ayarlar = require __DIR__ . '/form-ayarlar.php';

function cevap(bool $ok, string $mesaj, int $kod = 200): void {
    $ajax = ($_SERVER['HTTP_X_REQUESTED_WITH'] ?? '') === 'XMLHttpRequest'
         || str_contains($_SERVER['HTTP_ACCEPT'] ?? '', 'application/json');
    if ($ajax) {
        http_response_code($kod);
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode(['ok' => $ok, 'message' => $mesaj], JSON_UNESCAPED_UNICODE);
    } else {
        $geri = $_POST['page_url'] ?? '/';
        // Yalnızca site içi yol: "/..." kabul, "//baska-site" ve "/\\" reddedilir (açık yönlendirme koruması)
        $geri = (is_string($geri) && preg_match('#^/(?![/\\\\])[A-Za-z0-9/_\-.%]*$#', $geri)) ? $geri : '/';
        header('Location: ' . $geri . ($ok ? '?gonderildi=1' : '?hata=1'), true, 303);
    }
    exit;
}

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') cevap(false, 'Method not allowed', 405);

// Başka sitelerden gönderimi reddet (tarayıcı Origin/Referer gönderiyorsa kendi alan adımız olmalı)
$host   = strtolower(preg_replace('/:\d+$/', '', (string)($_SERVER['HTTP_HOST'] ?? '')));
$kaynak = $_SERVER['HTTP_ORIGIN'] ?? ($_SERVER['HTTP_REFERER'] ?? '');
if ($kaynak !== '' && strtolower((string)parse_url($kaynak, PHP_URL_HOST)) !== $host) cevap(false, 'Forbidden', 403);

// Aşırı büyük gönderimleri reddet
if ((int)($_SERVER['CONTENT_LENGTH'] ?? 0) > 100000 || count($_POST, COUNT_RECURSIVE) > 60) cevap(false, 'Payload too large', 413);

$wp     = $_POST['wpforms'] ?? [];
$formId = (string)($wp['id'] ?? '');
if (!isset($ayarlar[$formId])) cevap(false, 'Unknown form', 400);
$form = $ayarlar[$formId];

// Bot koruması: gizli alan (honeypot) dolu ise sessizce "başarılı" de
if (!empty($wp['hp'])) cevap(true, $form['basari']);

// Basit hız sınırı: aynı IP'den 60 sn içinde en fazla 3 gönderim
$ip   = $_SERVER['REMOTE_ADDR'] ?? '0';
$tmp  = sys_get_temp_dir() . '/vanterm_form_' . md5($ip);
$zaman = array_filter((array)@json_decode((string)@file_get_contents($tmp), true), function ($t) { return $t > time() - 60; });
if (count($zaman) >= 3) cevap(false, $form['hata'], 429);
$zaman[] = time();
@file_put_contents($tmp, json_encode(array_values($zaman)));

$gelen   = is_array($wp['fields'] ?? null) ? $wp['fields'] : [];
$satirlar = [];
$eposta  = '';
foreach ($form['alanlar'] as $id => $alan) {
    $deger = $gelen[$id] ?? '';
    if (is_array($deger)) $deger = $deger ? 'Evet / Yes' : '';
    $deger = trim(str_replace(["\r\n", "\r"], "\n", (string)$deger));
    $deger = mb_substr($deger, 0, 5000);
    if ($alan['zorunlu'] && $deger === '') cevap(false, $form['hata'], 422);
    if ($alan['tip'] === 'email') {
        if ($deger !== '' && !filter_var($deger, FILTER_VALIDATE_EMAIL)) cevap(false, $form['hata'], 422);
        $eposta = $deger;
    }
    $satirlar[] = '<tr><th align="left" valign="top" style="padding:6px 12px;background:#f4f4f4">'
        . htmlspecialchars($alan['etiket']) . '</th><td style="padding:6px 12px">'
        . nl2br(htmlspecialchars($deger)) . '</td></tr>';
}

$sayfa = htmlspecialchars((string)($_POST['page_url'] ?? ''));
$govde = '<html><body style="font-family:Arial,sans-serif;font-size:14px">'
    . '<h2>' . htmlspecialchars($form['ad']) . '</h2>'
    . '<table cellspacing="0" style="border-collapse:collapse;border:1px solid #ddd">' . implode('', $satirlar) . '</table>'
    . '<p style="color:#888">Sayfa: https://vanterm.com' . $sayfa . '<br>IP: ' . htmlspecialchars($ip) . '<br>' . date('d.m.Y H:i') . '</p>'
    . '</body></html>';

$konu = '=?UTF-8?B?' . base64_encode(SITE . ' - ' . $form['ad']) . '?=';
$basliklar = [
    'MIME-Version: 1.0',
    'Content-Type: text/html; charset=UTF-8',
    'From: ' . SITE . ' <' . GONDEREN . '>',
];
if ($eposta !== '') $basliklar[] = 'Reply-To: ' . $eposta;

$ok = @mail(ALICI, $konu, $govde, implode("\r\n", $basliklar), '-f' . GONDEREN);

// Teşhis kaydı (web kökünün DIŞINDA; kişisel veri yazılmaz): tarih, form, mail() sonucu, hata
$hata = $ok ? '' : (string)(error_get_last()['message'] ?? '');
@file_put_contents(dirname(__DIR__) . '/vanterm-form.log',
    date('Y-m-d H:i:s') . ' | ' . $form['ad'] . ' | mail()=' . ($ok ? 'OK' : 'BASARISIZ') . ($hata !== '' ? ' | ' . $hata : '') . "\n",
    FILE_APPEND | LOCK_EX);
$ok ? cevap(true, $form['basari']) : cevap(false, $form['hata'], 500);

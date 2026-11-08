# Vanterm statik web sitesi

vanterm.com'un WordPress'ten statik HTML/CSS/JS'e çevrilmiş hâli. Tasarım, renkler, metinler ve adresler (URL) orijinalle birebir aynıdır.

- **`site/`** → sunucuda `public_html` içine giden sitenin kendisi (232 sayfa, EN + TR)
- **`deploy/`** → sunucunun GitHub'dan otomatik güncelleme yapmasını sağlayan dosyalar
- **`tools/`** → dönüştürme ve kontrol araçları (yalnızca geliştirme için, sunucuya gitmez)

## Nasıl çalışır

```
Claude (veya sen) site/ içinde değişiklik yapar → GitHub'a gönderir (push)
      → sunucudaki cron her 5 dakikada GitHub'ı kontrol eder
      → yeni değişiklik varsa çeker ve site/ içeriğini public_html'e kopyalar
```

Sunucu şifresi kimseyle paylaşılmaz. Sunucu, GitHub'dan yalnızca okuma yetkisiyle çeker.

---

## cPanel kurulumu — önce demo.vanterm.com (bir kez, ~20 dakika)

Site önce **demo.vanterm.com** adresinde yayınlanır. Mevcut WordPress sitesine (vanterm.com) dokunulmaz.
Demo, arama motorlarına kapalıdır (robots.txt engeli + `noindex` başlığı). İstenirse şifreyle korunur.
Hangi adrese yayın yapılacağı `deploy/hedef.conf` dosyasında yazılıdır.

### 1. Alt alan adını aç
cPanel → **Domains → Create A New Domain**
- Domain: `demo.vanterm.com`
- "Share document root" kutusu: **kapalı**
- Document Root: `demo.vanterm.com` (public_html'in **dışında**, ev dizininde)
- **Submit**

Ardından cPanel → **SSL/TLS Status → Run AutoSSL**. Demo adresinin sertifikası birkaç dakika içinde gelir.

### 2. GitHub okuma anahtarı oluştur
GitHub → sağ üst profil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Token name: `vanterm-cpanel`
- Expiration: istediğin süre (süre dolunca yenisi gerekir)
- Repository access: **Only select repositories → airoomier/vanterm**
- Permissions → Repository permissions → **Contents: Read-only**
- **Generate token** → çıkan `github_pat_...` değerini kopyala (bir daha gösterilmez).

### 3. Depoyu sunucuya klonla
cPanel → **Git™ Version Control → Create**
- Clone a Repository: **açık**
- Clone URL: `https://github_pat_BURAYA_TOKEN@github.com/airoomier/vanterm.git`
- Repository Path: `repositories/vanterm`
- Repository Name: `vanterm`
- **Create**

### 4. İlk yayın
Git Version Control → vanterm → **Manage → Pull or Deploy** → **Deploy HEAD Commit**.
https://demo.vanterm.com açılmalı (İngilizce). Türkçe: https://demo.vanterm.com/tr/

### 5. Otomatik güncelleme (cron)
cPanel → **Cron Jobs** → Common Settings: **Once Per Five Minutes (*/5)**
Command:
```
/bin/bash $HOME/repositories/vanterm/deploy/auto-deploy.sh >/dev/null 2>&1
```
**Add New Cron Job**. Dağıtım geçmişi `~/vanterm-deploy.log` dosyasına yazılır.

### 6. Form e-postası
E-postalar ofis.net'te barındırılıyor (MX: mx01/mx02.ofis.net); form mailleri **bilgi@vanterm.com**'a gider.
- cPanel → **E-posta Yönlendirme (Email Routing)** → vanterm.com → **Uzak Posta Sunucusu (Remote Mail Exchanger)** seçili olmalı.
  Aksi hâlde cPanel mailleri yerel kutuya teslim eder ve ofis.net'e ulaşmaz.
- cPanel'de vanterm.com posta kutusu **açılmamalı**.
- SPF (`include:_spf.trwww.com`) web sunucusunu kapsıyor; ek DNS ayarı gerekmez.

### 7. (İsteğe bağlı) Demoyu şifreyle koru
cPanel → **Directory Privacy** → `demo.vanterm.com` klasörü → "Password protect this directory" → kullanıcı adı ve şifre oluştur.
Ardından Git Version Control → **Deploy HEAD Commit** ile bir kez yeniden yayınla. Şifre, sonraki tüm güncellemelerde korunur.
Firmaya adresle birlikte kullanıcı adı ve şifreyi ver.

### 8. Kontrol listesi
- [ ] https://demo.vanterm.com ve /tr/ açılıyor
- [ ] Bir ürün sayfasında PDF indirme çalışıyor
- [ ] İletişim ve Ürün Kaydı formları (EN ve TR) gönderiliyor, form@vanterm.com'a mail geliyor
- [ ] Sağ üstteki arama çalışıyor
- [ ] https://demo.vanterm.com/robots.txt içinde `Disallow: /` var

---

## Canlıya geçiş (firma onaylayınca)

1. cPanel → **Yedekleme**: `public_html` ve WordPress veritabanı yedeği.
2. Dosya Yöneticisi (gizli dosyalar açık): ev dizininde `wp-yedek` klasörü aç. `public_html` içindeki her şeyi **`.well-known` ve `cgi-bin` hariç** oraya taşı.
3. Claude'a "canlıya al" de. Claude `deploy/hedef.conf` dosyasını `HEDEF="public_html"`, `MOD="canli"` yapıp gönderir. En geç 5 dakika içinde site vanterm.com'da yayında olur.
4. Kontrol: https://vanterm.com, https://www.vanterm.com → vanterm.com yönlenmesi, formlar, PDF'ler, https://vanterm.com/sitemap_index.xml
5. Google Search Console → Site Haritaları → `https://vanterm.com/sitemap_index.xml` gönder.
6. Demo alt alan adı istenirse cPanel → Domains'den silinir.

## Güncelleme yapmak

`site/` içindeki HTML dosyaları doğrudan düzenlenir, commit edilip `main` dalına gönderilir. En geç 5 dakika içinde canlıya çıkar.

- Sunucudan bir dosya silinecekse yolunu `deploy/silinecekler.txt` dosyasına ekle (kopyalama işlemi dosya silmez).
- Yayın adresi (demo / canlı): `deploy/hedef.conf`.
- Form alıcısı: `site/form-gonder.php` içindeki `ALICI` (bilgi@vanterm.com; gönderen form@vanterm.com, yanıtla = ziyaretçi).
- Form başarı/hata metinleri: `site/form-ayarlar.php`.
- Değişiklikten sonra kontrol: `python3 tools/check.py` (kırık iç link taraması).

## Teknik notlar

- Adresler WordPress ile aynı: klasör + `index.html` (`/product/pm-series-filter-units/`).
- Orijinal sitedeki 57 adet 301 yönlendirmesi `.htaccess` içine taşındı (`tools/redirects.json`).
- SEO: title, description, canonical, Open Graph, Yoast şemaları korundu, adresler `https://vanterm.com` yapıldı. EN↔TR sayfalara `hreflang` eklendi (x-default: İngilizce).
- Etiket, kategori ve gizlilik sayfalarındaki `noindex` orijinaldeki gibi korundu.
- Formlar: WPForms işaretlemesi ve tasarımı aynen duruyor; gönderim `form-gonder.php` (PHP `mail()`) üzerinden. Bot koruması: gizli alan + IP başına dakikada 3 gönderim.
- Arama: `/search/?s=...` ve `/tr/search/?s=...` statik arama (`search-index.json`). Eski `/?s=` adresleri buraya yönlenir.
- `tools/build.py` ilk dönüştürmeyi yapan araçtır. Site artık `site/` üzerinden düzenlendiği için tekrar çalıştırılması gerekmez. Çalıştırılırsa `site/` içindeki elle yapılmış değişiklikler silinir.

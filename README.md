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

## cPanel kurulumu (bir kez yapılır, ~20 dakika)

### 1. Yedek al
cPanel → **Yedekleme (Backup)** → `public_html` klasörünün ve WordPress veritabanının yedeğini indir.

### 2. GitHub okuma anahtarı oluştur
GitHub → sağ üst profil → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
- Token name: `vanterm-cpanel`
- Expiration: istediğin süre (ör. 1 yıl; süre dolunca yenisi gerekir)
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

### 4. WordPress dosyalarını kenara al
cPanel → **Dosya Yöneticisi** → Ayarlar → "Gizli dosyaları göster" açık.
1. Ana dizinde (`public_html`'in bir üstü) `wp-yedek` adında klasör oluştur.
2. `public_html` içindeki her şeyi seç, **ama `.well-known` ve `cgi-bin` klasörlerini seçme**.
3. **Taşı (Move)** → hedef: `/wp-yedek`.

> Site birkaç dakika boş kalır. Bunu trafiğin az olduğu bir saatte yap.

### 5. İlk yayın
cPanel → **Git Version Control** → vanterm → **Manage → Pull or Deploy** → **Deploy HEAD Commit**.
Ardından https://vanterm.com açılmalı (İngilizce). Türkçe: https://vanterm.com/tr/

### 6. Otomatik güncelleme (cron)
cPanel → **Cron Jobs** → Common Settings: **Once Per Five Minutes (*/5)**
Command:
```
/bin/bash $HOME/repositories/vanterm/deploy/auto-deploy.sh >/dev/null 2>&1
```
**Add New Cron Job**. Dağıtım geçmişi `~/vanterm-deploy.log` dosyasına yazılır.

### 7. Form e-postası
cPanel → **Email Accounts → Create** → `form@vanterm.com`.
cPanel → **Email Deliverability** → vanterm.com için SPF ve DKIM "Valid" olmalı (değilse **Repair**). Böylece form mailleri spama düşmez.

### 8. Kontrol listesi
- [ ] https://vanterm.com ve https://vanterm.com/tr/ açılıyor
- [ ] https://www.vanterm.com → https://vanterm.com yönleniyor
- [ ] Bir ürün sayfasında PDF indirme çalışıyor
- [ ] İletişim formu (EN ve TR) gönderiliyor ve form@vanterm.com'a mail geliyor
- [ ] Ürün kaydı formu (EN ve TR) çalışıyor
- [ ] Sağ üstteki arama çalışıyor
- [ ] https://vanterm.com/sitemap_index.xml açılıyor

### 9. Google Search Console
Site Haritaları → `https://vanterm.com/sitemap_index.xml` gönder.

---

## Güncelleme yapmak

`site/` içindeki HTML dosyaları doğrudan düzenlenir, commit edilip `main` dalına gönderilir. En geç 5 dakika içinde canlıya çıkar.

- Sunucudan bir dosya silinecekse yolunu `deploy/silinecekler.txt` dosyasına ekle (kopyalama işlemi dosya silmez).
- Form alıcısı: `site/form-gonder.php` içindeki `ALICI`.
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

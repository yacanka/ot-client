# OT Desktop

Windows için hafif belge arama ve indirme uygulaması. Mevcut OT istemcinizin uç noktalarını kullanır; belge listesini ve bağlantı ayarlarını masaüstünden yönetir.

## Hızlı başlangıç

1. ZIP dosyasını kullanıcı hesabınızın yazabildiği bir klasöre çıkarın.
2. Bilgisayarda **Python 3.10 veya üzeri**, Tcl/Tk ve pip bulunmalıdır. Python 3.11+ kullanılabilir. Python yükleyicisinin Tcl/Tk seçeneğini açık bırakın.
3. İlk kullanımda **Kurulum.cmd** dosyasını çalıştırın. Script önce Python 3.11'i, yoksa uygun Python 3 sürümünü bulur; uygulama klasöründe `.venv` oluşturur ve `requirements.txt` içindeki paketi kurar. Paket kurulumu için internet veya kurumunuzun Python paket deposuna erişim gerekir.
4. **Baslat.cmd** ile uygulamayı açın. Sonraki açılışlarda kurulum tekrarlanmaz.
5. **Bağlantı / Ayarlar** bölümünden sunucu adresini, kullanıcı adını, parolayı ve indirme klasörünü girin. Parola ve kullanıcı adı normal metin olarak girilir; önceden kodlamayın.
6. **Ayarları kaydet** ve **Bağlantıyı test et** düğmelerini kullanın. Giriş işlemi yanında belge arama servisinin erişimi de kontrol edilir.
7. **Belgeler** ekranına dönün, belge numaralarını ekleyin ve **Listeyi indir** düğmesine basın.

`Baslat.cmd` yönetici izni istemez. Python kurulumu bilgisayarınızda yoksa Python'un ayrıca kurulması gerekir; CMD dosyaları Python yüklemez.

### Mevcut Python ortamınızla

CMD kurulumunu kullanmak zorunda değilsiniz. Uygulama klasöründe:

```bat
py -3.11 -m pip install -r requirements.txt
py -3.11 OT_desktop.pyw
```

Başka bir uygun Python seçtiyseniz aynı komutlarda onu kullanın. `python OT_desktop.pyw` da etkin ortamla çalışır. `Baslat.cmd` ise uygulamanın kendi `.venv` ortamını kullanır.

## Belge listesi

| İşlem | Kullanım |
|---|---|
| Tek belge ekleme | Numarayı yazın; Enter veya Ekle düğmesini kullanın. |
| Toplu ekleme | Toplu ekle penceresine Excel'den veya metin dosyasından yapıştırın. Eklemeden önce benzersiz belge sayısını görün. |
| Dosyadan alma | TXT, CSV, TSV veya JSON dosyası seçin. `.xlsx` dosyasından hücreleri kopyalayıp Toplu ekle alanına yapıştırın. |
| Çoklu seçim | Ctrl ve Shift ile seçin. Ctrl+A yalnızca filtrede görünen satırları seçer. |
| Silme | Seçileni kaldır veya Delete. İndirilen dosyalar silinmez. |
| Geri alma | Liste işlemleri → Son kaldırmayı geri al; liste odaktayken Ctrl+Z. Son kaldırma geri alınabilir. |
| Listeyi temizleme | Liste işlemleri → Tüm listeyi temizle. |
| Listeyi dışa aktarma | Liste işlemleri → Listeyi dışa aktar. Seçim varsa seçili belgeler, yoksa tüm liste aktarılır. |
| Sonuç raporu | Liste işlemleri → Sonuç raporunu dışa aktar. Excel uyumlu UTF-8 BOM ve noktalı virgülle CSV üretir. |
| Kopyalama | Liste odaktayken Ctrl+C seçili belge numaralarını kopyalar. |
| Listede arama | Filtre alanına yazın veya Ctrl+F. Belge numarası, başlık ve açıklama aranır. |
| Seçili indirme | Seçileni indir. Tüm listeyi yeniden çalıştırmak için Listeyi indir. |
| Yeniden deneme | Liste işlemleri → Sorunluları yeniden dene. Eşleşme seçimi gereken satırlar ayrı ele alınır. |
| Durdurma | Durdur. Bekleyen işler iptal edilir; sürmekte olan ağ isteğinin yanıtı/zaman aşımı beklenebilir. |
| Dosyayı açma | Satırı seçip Dosyayı aç veya çift tıklama. |

### Kabul edilen toplu girişler

Her satır bir belge:

```text
PR-001
PL-028
FR-106
```

Ayraçlı metin:

```text
PR-001; PL-028; FR-106
```

JSON metin dizisi:

```json
["PR-001", "PL-028", "FR-106"]
```

Satır sonu, sekme, virgül ve noktalı virgül desteklenir. Tırnak içindeki ayraçlar ve çok satırlı hücreler korunur. Başlangıç/bitiş boşlukları temizlenir. Tekrarlar giriş sırası korunarak ayıklanır; büyük/küçük harf farklılığı ve baştaki sıfırlar korunur. JSON dizisindeki elemanlar metin olmalıdır; örneğin `[123]` geçerli değildir.

TXT ve JSON dışa aktarımları tekrar içe alınabilir. CSV'de formül gibi yorumlanabilecek değerlerin önüne yalnızca dışa aktarılan kopyada apostrof konur. Bu CSV tekrar alınırsa apostrof da alınır; eksiksiz liste alışverişinde TXT veya JSON kullanın. Girdi dosyası başlığı otomatik tahmin edilmez; ilk satırdaki başlık varsa listeye belge olarak eklenir, hücreleri başlıksız kopyalayın.

Liste sınırları: 10.000 benzersiz numara, numara başına 1.024 karakter, toplam 5.242.880 girdi karakteri ve 10 MiB içe aktarma dosyası. Büyük listelerde satır bazında görünüm kaydırılır; küçük pencere boyutlarında özet kartları tek satıra dönüşür.

## İşlem sonuçları

| Durum | Anlamı |
|---|---|
| Bekliyor | İşleme alınmadı. |
| Aranıyor / İndiriliyor | Arka plandaki iş sürüyor. |
| İndirildi | Yeni dosya kaydedildi. |
| Güncellendi | Yerel dosya farklıydı ve yeni içerikle değiştirildi. |
| Güncel | Gelen içerik ile yerel dosyanın SHA256 değeri aynı; dosya yeniden yazılmadı. |
| Bulunamadı | Arama sonucu boş. |
| Seçim gerekli | Birden fazla belirsiz sonuç bulundu. Satırı seçin, Eşleşmeyi seç ile doğru belgeyi belirleyin; ardından Seçileni indir kullanın. |
| Hata | Satırdaki açıklamayı kontrol edip yeniden deneyin. |
| İptal edildi | Durdurma nedeniyle tamamlanmadı. |

Tam belge adıyla tek eşleşme varsa o tercih edilir. Tek benzersiz sonuç da kullanılabilir. Birden fazla belirsiz sonuçta ilk kayıt otomatik indirilmez. Seçtiğiniz aday o oturum boyunca korunur.

**Güncel** kararı indirme tamamlandıktan sonra SHA256 karşılaştırmasıyla verilir. Bu sürüm sunucunun ETag/Last-Modified desteğine dayanmaz; dolayısıyla aynı dosyayı kontrol ederken ağdan veri yine alınır. Dosyalar tek tek işlenir; eşzamanlı indirme yapılmaz.

## Ayarlar ve kayıt defteri

Kullanıcıya ait konum:

```text
HKEY_CURRENT_USER\Software\OTDesktop
```

| Kayıt | Tür | İçerik |
|---|---|---|
| Settings | REG_SZ | Sunucu adresi, kullanıcı adı, hedef klasör, zaman aşımı, klasör kimliği ve TLS/CA seçenekleri. Parola içermez. |
| Documents | REG_MULTI_SZ | Belge numaraları. |
| Password | REG_BINARY | Windows DPAPI ile geçerli kullanıcı hesabına bağlı şifrelenmiş parola. |

Belge listesi değişiklikleri kısa bir gecikmeyle otomatik kaydedilir. Ayarlar Kaydet, Bağlantıyı test et ve indirme başlatılırken kaydedilir; geçerli ve değiştirilmiş ayarlar normal kapanışta da saklanır. Kayıt hataları görünür kalır. Okunamamış fakat değiştirilmemiş belge listesi, ayar kaydında veya kapanışta boş listeyle değiştirilmez.

Parolayı hatırla seçeneğini kapatıp kaydederseniz saklanan parola silinir. Hatırlama açıkken parola alanını boş bırakmak eski şifreli kaydı korur; parolayı kaldırmak için seçeneği kapatın. Kayıt defterine düz metin parola veya Base64 yazılmaz. DPAPI bir erişim izni sistemi değildir: sizin Windows oturumunuzdaki uygulamalara karşı ayrı bir güvenlik sınırı oluşturmaz. Şifreli değeri başka bir bilgisayara/kullanıcıya taşımak genellikle işe yaramaz; o ortamda parolayı yeniden girin.

Windows dışında uygulama test/geliştirme amacıyla açılabilir; kayıt defteri yerine açıkça belirtilen geçici oturum modu kullanılır. Bu modda ayarlar diske kaydedilmez.

### Gelişmiş ayarlar

- **Zaman aşımı:** Her ağ isteğinin bağlantı/okuma bekleme süresi. Toplam iş süresi sınırı değildir. Varsayılan 30 saniye.
- **Klasör kimliği:** İstemcinin mevcut klasör listeleme metodu için opsiyonel parametre. Ana arama/indirme akışı kullanmaz.
- **CA sertifika dosyası:** Kurumun HTTPS sertifikasını doğrulamak için isteğe bağlı PEM CA paketi.
- **TLS doğrulama:** Varsayılan açık. İhtiyaç halinde kullanıcı arayüzünden değiştirilebilir; kurumsal CA paketi tercih edilebilir.

## İstemcide değişen davranışlar

- `.env`, `BASE_URL`/`USERNAME`/`PASSWORD` ortam değişkenleri, Base64 çözme ve modül içe aktarılırken çalışan ağ işlemleri kaldırıldı.
- Kullanılmayan `tabulate`, `dotenv`, `pprint` bağımlılıkları kaldırıldı. Tek dış çalışma bağımlılığı `requests`.
- Giriş formu alanları ve mevcut `/TDS/...` uç noktaları korundu; kimlik bilgileri açık parametrelerdir.
- Girişten sonra korumalı arama servisi doğrulanır; HTTP 200 tek başına giriş başarısı sayılmaz.
- İstemci açıklanabilir hatalar ve yapılandırılmış sonuç döndürür; UI bunları gösterir.
- Dosya uzantısı korunur veya sunucu dosya adı/MIME bilgisine göre belirlenir. `POL.001` gibi numaraların sayısal son bileşeni uzantı sayılmaz. Her dosyaya `.docx` eklenmez.
- İndirme 64 KiB parçalarla geçici dosyaya yapılır. Tamamlanma, uygun boyut kontrolü ve SHA256 karşılaştırması sonrasında atomik değiştirme uygulanır. Ağ kesintisi veya iptal, mevcut dosyayı bozmaz.
- İstenmeyen JSON/HTML servis yanıtları ve 204/205/206 gibi tam dosya olduğunu kanıtlamayan yanıtlar reddedilir. Açıkça JSON/HTML dosyası olarak belirtilen gerçek belgeler desteklenir.
- Windows için geçersiz/ayrılmış dosya adları temizlenir. Aynı işlemde farklı belgelerin aynı adla çakışması sessizce üzerine yazmaya dönüşmez.

**Adlandırma sınırı:** Normal dosya adları korunur. Farklı oturumlarda aynı normal dosya adını kullanan iki ayrı belge kimliğini saptamak için kalıcı bir kimlik indeksi tutulmaz. Böyle belgeleri farklı hedef klasörlere indirin. Otomatik yönlendirmeler izlenmez; kurumdaki medya servisi ayrıca başka bir dosya sunucusuna yönlendiriyorsa o akış, gerçek yanıtına göre uyarlanmalıdır.

### Programatik kullanım

```python
from OTClient import OTConnector

with OTConnector(
    base_url="https://OT.kurumunuz.com",
    username="kullanici",
    password="gercek-parola",
    timeout=30,
) as client:
    client.login()
    candidates = client.search_documents("PR-001")
    if len(candidates) == 1:
        document = candidates[0]
        result = client.download_document(
            document.id,
            folder_path="OT Documents",
            file_name=document.name,
        )
        print(result.status, result.path)
```

Örnekteki değerleri kendi çağıran uygulamanızdan sağlayın; gerçek parolayı kaynak koda yerleştirmeyin. `search_document()` ham JSON için korunmuştur. `download_document()` artık boolean yerine `DownloadResult` döndürür; `status` alanı `downloaded`, `updated` veya `unchanged` olabilir. Hatalar `OTError`, iptal `DownloadCancelled` ile bildirilir. Aynı istemciyi birden çok iş parçacığında paylaşmayın.

## Kurumsal ağ ve çevrimdışı kurulum

Uygulamanın web arayüzü veya yerel sunucu bileşeni yoktur. Belge aramak ve indirmek için OT sunucusuna erişmek gerekir; kayıtlı liste ve ayarlar internet olmadan açılabilir. Mevcut requests proxy davranışı geçerlidir; ayrıca NTLM/SSO entegrasyonu eklenmemiştir. Orijinal istemcideki form tabanlı OT girişi kullanılır.

İnternete erişebilen, hedef bilgisayarla uyumlu bir Windows/Python ortamında:

```bat
py -3.11 -m pip download -r requirements.txt -d wheels
```

Paket klasörünü uygulamayla birlikte hedefe taşıyın. Hedefte:

```bat
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --no-index --find-links wheels -r requirements.txt
```

Ardından `Baslat.cmd` çalıştırılabilir. Kurumunuzun paket deposu varsa onun pip yapılandırmasını da kullanabilirsiniz.

## Doğrulama

Teslim edilen test takımında **169 test çalıştırıldı: 168 geçti, 1 test atlandı**.

- İstemci: sahte taşıyıcı senaryoları ve gerçek yerel HTTP sunucusuyla oturum çerezi, yanlış parola, kesilmiş yanıt, hata medyası ve dosya koruma kontrolleri.
- Kalıcılık: kayıt defteri sınırında sahte yerel hizmetlerle okuma/yazma, bozulma, hatırlamayı kapatma ve kuyruk koruma kontrolleri; ctypes imzaları/bellek temizliği.
- Belge girdisi: ayrıştırma, tırnaklar, Türkçe/Unicode, dosya kodlamaları, tekrarlar, sınırlar ve güvenli dışa aktarım.
- Gerçek Tk penceresi: seçim, silme, geri alma, filtre, bağlantı/test akışı, tüm işin arka planda tamamlanması, durdurma/kapanış olayları, küçük ekran, ayar ve toplu giriş pencereleri.

Testler Linux üzerinde gerçek Tk penceresiyle çalıştırıldı. Atlanan tek test, **gerçek Windows kullanıcısının DPAPI turunu** gerektirir. Windows kayıt defteri/DPAPI gerçek çalıştırması, CMD dosyalarının Windows üzerinde yürütülmesi ve kurumunuzun gerçek OT bağlantısı burada denenemedi. Ekran görüntüleri gerçek uygulama pencerelerinden alınmıştır; görünen belge numaraları/sonuçları örnek veridir.

Windows üzerinde testleri çalıştırmak için:

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Testler gerçek OT hesabına bağlanmaz. Açılan test pencereleri otomatik kapanır. DPAPI testi gerçek Windows hesabında çalışır ve üretim OT kayıtlarını değiştirmez.

## Dosya yapısı

- `OT_desktop.pyw`: masaüstü giriş noktası.
- `OTClient.py`: arayüzden bağımsız HTTP istemcisi.
- `OT_app/`: ayarlar, Windows parola koruma, liste yönetimi, arka plan işi ve UI bileşenleri.
- `tests/`: otomatik testler.
- `docs/`: tasarım/uygulama notları ve doğrulama özeti.
- `previews/`: örnek verilerle alınmış gerçek pencere görüntüleri.
- `Kurulum.cmd`, `Baslat.cmd`, `requirements.txt`: Windows kurulumu ve açılış.

## Başvuru

- Python Tkinter: https://docs.python.org/3/library/tkinter.html
- Windows kayıt defteri API: https://docs.python.org/3/library/winreg.html
- Microsoft DPAPI: https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata

# XYZA Toolpath

**XYZA Toolpath**, Mach3 tabanlı CNC makineler için geliştirilmiş,
özellikle **teğetsel bıçak (A ekseni)** kullanan sistemlere odaklanan
bir **CAM / toolpath üretim** masaüstü uygulamasıdır.

Proje; 2D ve 3D geometrilerden takım yolu üretir, bıçak yönünü (A ekseni)
otomatik hesaplar, simüle eder ve Mach3’te doğrudan çalışabilecek
**G-code (.nc)** çıktısı üretir.

XYZA, özellikle **ultrasonik bıçak**, **mekanik teğetsel bıçak** ve
benzeri özel kesim sistemleri için tasarlanmıştır.

---

## 🎯 Temel Amaç

- Teğetsel bıçaklı CNC sistemlerde **doğru bıçak yönü (A ekseni)** üretmek
- 2D yol mantığını 3D takım yoluna **kararlı ve pürüzsüz** şekilde aktarmak
- Mach3 için **güvenli, okunabilir ve kontrol edilebilir G-code** üretmek
- Kullanıcıya hem **2D hem 3D** önizleme ile tam kontrol sağlamak

---

## ✨ Özellikler

### Genel
- 2D ve 3D takım yolu üretimi
- Gerçek zamanlı 3D simülasyon
- Portable yapı (INI dosyaları exe yanında çalışır)
- Windows masaüstü uygulaması (PyQt)

### A Ekseni / Teğetsel Bıçak
- XY teğet yönüne göre otomatik A ekseni hesaplama
- A açıları için normalize / unwrap ve smoothing
- Köşe algılama ve pivot davranışı
- 45° üzeri dönüşlerde güvenli Z retract
- Disk, scalpel ve özel bıçak tipleri için altyapı

### G-code
- Mach3 uyumlu G-code
- G21 / G90 / G17 / G94
- G53 → G54 güvenli başlangıç akışı
- Modal yazım (gereksiz tekrar yok)
- A ekseni ve spindle komutları ayarlardan kontrol edilebilir

---

## 🧭 Desteklenen Kullanım Senaryoları

- Teğetsel bıçaklı CNC makineler
- Ultrasonik bıçak sistemleri
- Deri, tekstil, eva, conta, karton kesimi
- Mach3 kontrol yazılımı kullanan tezgâhlar

---

## 🛠️ Tipik Kullanım Akışı

1. Model yükle (STL / DXF)
2. 2D veya 3D takım yolunu oluştur
3. **A Ekseni Ekle** ile bıçak yönlerini hesapla
4. Önizlemeleri kontrol et
5. G-code (.nc) oluştur
6. Mach3’te çalıştır

---

## ⚙️ G-code Örneği

```gcode
G1 X62.123 Y406.999 Z-1.000 A15.196 F1000
```

---

## 🧩 A Ekseni Mantığı

- 2D sekmesinde A açıları teğetsel yön ve smoothing/pivot polish ile üretilir.
- 3D takım yolu yalnızca XYZ üretir; A sonradan **attach** edilir (arc-length veya yakın komşu eşleme).
- Export sırasında `output_axes=XYZA` ise A modal olarak aynı satırda yazılır; küçük değişimler `a_min_step_deg` ile filtrelenir.
- Turn-retract kuralı: kesim sırasında 45°+ dönüşlerde Z safe’ye çık, A’yı çevir, Zcut’a dön.

---

## 🖥️ Mach3 Davranışı ve Modal Yazım

- Başlangıç: G21 G90 G17 G94, ardından opsiyonel G53 park, sonra G54.
- Rapid: `G0 X.. Y.. Z..` (A gerekiyorsa eklenir, F yazılmaz).
- Cut: `G1 X Y Z A F` sıralı, modal; değişmeyen eksen/Feed yazılmaz.
- Spindle ayarları: `spindle_enabled`, `spindle_use_s`, `spindle_rpm`, `spindle_on_mcode`, `spindle_off_mcode`.

---

## 🧳 Portable Config ve G53 Park

- Uygulama, ini dosyalarını önce exe yanındaki konumda, yoksa `%APPDATA%/ZYZA/` altında arar; yoksa `resources/default_*.ini` kopyalanır.
- G53 park parametreleri: `use_g53_park`, `g53_park_x/y/z`, (opsiyonel `g53_park_a`).
- Çalışma offseti G54 ile devam eder.

---

## 🚀 Kurulum ve Çalıştırma

### Kaynaktan
- Python 3.11 tavsiye edilir.
- Bağımlılıklar: `python -m pip install -r requirements.txt`
- Çalıştır: `python main.py`

### Windows EXE (PyInstaller)
- Derle: `pyinstaller build\\xyza.spec --noconfirm --clean`
- Alternatif: `powershell -ExecutionPolicy Bypass -File tools\\build_exe.ps1`
- Çalıştır: `dist\\XYZA\\XYZA.exe` (portable ini desteği ile)

---

## 🗂️ Dizin Yapısı (özet)

- `core/`, `gui/`, `tabs/`: Uygulama kodları ve UI sekmeleri
- `resources/`: Varsayılan ini ve görseller
- `build/xyza.spec`: PyInstaller spec (XYZA.exe)
- `tools/build_exe.ps1`, `tools/build_doctor.py`: Derleme yardımcıları
- `icons/`, `images/`: UI varlıkları

---

## 🆘 Sorun Giderme

- PyInstaller’da çoklu Qt uyarısı: Ortamda yalnızca **PyQt5** olmalı; PyQt6/PySide’ı kaldır veya spec’te exclude et.
- INI hatası (ör. WINDOW anahtarı yok): `settings.ini`yi silip uygulamanın varsayılanı yeniden oluşturmasına izin ver.
- Eksik kaynak dosyası: portable ini ve `resources/default_*.ini` paketlendiğinden exe ile aynı klasörde olduklarını doğrula.

---

## Binary Releases

- Kaynak kod repoda tutulur; Windows EXE GitHub Releases altında paylaşılır.
- Portable zip paketinde `default_settings.ini` ve `default_tool.ini` yer alır.
- EXE repoya commitlenmez; release asset olarak yayınlanır.

## Build (Windows)

- `python -m pip install -r requirements.txt`
- `pyinstaller build\\xyza.spec --noconfirm --clean`
- `powershell -ExecutionPolicy Bypass -File tools\\release_package.ps1`

---

## 📜 Lisans

Bu proje **MIT License** ile lisanslanmıştır. Ayrıntılar için `LICENSE` dosyasına bakın.

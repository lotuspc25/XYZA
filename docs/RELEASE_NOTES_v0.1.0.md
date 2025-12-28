# XYZA Toolpath v0.1.0

Özet: STL → XY(Z) toolpath üretimi, 2D tabanlı A ekseni eşleme, Mach3 uyumlu G-code export, portable INI yapılandırması.

## Paket İçeriği (ZIP)
- XYZA.exe
- default_settings.ini
- default_tool.ini

## Kurulum ve Kullanım
1) ZIP'i açın (örn. `XYZA_Portable_v0.1.0.zip`).
2) Aynı klasördeki `default_settings.ini` ve `default_tool.ini` ile başlatın (portable).
3) `XYZA.exe` çalıştırın.
4) Model yükleyin, takım yolu oluşturun, “A Ekseni Ekle” deyin.
5) G-code (.nc) üretin ve Mach3’e aktarın.

## Notlar
- EXE repoya commitlenmez; GitHub Releases altında asset olarak paylaşılır.
- Portable yapı: INI dosyaları exe yanında bulunur; yoksa varsayılanlar kopyalanır.

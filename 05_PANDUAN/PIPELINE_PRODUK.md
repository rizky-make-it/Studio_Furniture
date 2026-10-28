# Pipeline produk: DWG → file produk .blend

Semua skrip ada di `99_SISTEM/pipeline/`. Jalankan dari mana saja; path hasil mengikuti struktur paket. Python yang dipakai: `C:\Program Files\Blender Foundation\Blender 5.2\5.2\python\bin\python.exe` (tanpa dependensi tambahan) atau Blender headless.

## Alur satu produk

1. **Siapkan folder produk**: `02_PRODUK/<Kategori>/<Nama_Folder>/sumber/`. Taruh gambar referensi (Pinterest, foto) di `sumber/referensi/`.
2. **Ekspor solid dari DWG** (butuh AutoCAD 2021):
   ```
   python 99_SISTEM/pipeline/dwg_ke_stl.py "<file.dwg>" "02_PRODUK/<Kat>/<Nama>/sumber/ekspor"
   ```
   Menghasilkan `solid_<i>.stl`, `parts.json` (handle, layer, warna per solid), `dwg_info.json` (INSUNITS, extents).
3. **Tulis `sumber/produk.json`** (contoh: `02_PRODUK/Nakas/Doheny_Side_Table/sumber/produk.json`):
   - `unit`: satuan angka DWG (`mm` biasanya, walau INSUNITS bilang inci).
   - `sumbu`: sumbu CAD yang menjadi atas dan depan. Doheny: `{"atas": "+Y", "depan": "+Z"}`. Bila salah, render QC akan terlihat rebah/terbalik; ganti lalu bangun ulang.
   - `part`: per handle DWG → `nama`, `peran` (`WOOD_A`, `WOOD_B`, `HANDLE`, `METAL`, `FELT`), `laci` (nomor laci bila ikut bergerak), `serat` (`X`/`Y`/`Z`, opsional), `min_cad` (opsional: sudut minimum part dalam koordinat DWG, `null` pada sumbu yang dibiarkan; dipakai bila STLOUT menghilangkan posisi X/Y seperti pada Doheny Tallboy), `skala` (opsional: skala part terhadap pusatnya, mis. `[1.4, 1, 1]` memanjangkan handle; diterapkan sebelum `min_cad`).
   - Satu produk boleh membawa beberapa entri `finish_kayu` dengan swatch sama tetapi `tekstur_dasar` berbeda (varian serat); semuanya muncul di dropdown finish studio.
   - `laci`: per nomor → `travel_m`, `kotak` (buat kotak laci sederhana), `celah_m`.
   - `finish_kayu`: daftar finish dari data produk (PDF/katalog klien atau foto sampel): `id`, `nama`, `sumber` {`pdf`, `halaman`, `obj`} atau `swatch` (file di `sumber/`), `tekstur_dasar` (id set Poly Haven yang terdaftar), `kilap`, `kalibrasi.gain_kontras`. Semua ditanam ke file produk dan bisa dipilih di studio.
   - `finish`: `default` (id finish kayu yang terpasang saat impor), `handle` (id hardware dari `_FINISH/finishes.json`).
   Jalankan dulu langkah 4 dengan `part` kosong: `sumber/ekspor/part_saran.json` berisi ukuran dan tebakan peran tiap handle untuk membantu pemetaan.
4. **Bangun produk**:
   ```
   blender -b --factory-startup --python 99_SISTEM/pipeline/bangun_produk.py -- "02_PRODUK/<Kat>/<Nama>/sumber/produk.json"
   ```
   Menghasilkan `<Nama_Folder>.blend` (UV meter, bevel, driver laci, material per peran, semua finish kayu produk ter-embed, tekstur packed) dan `INFORMASI.json`. Swatch dan tekstur terkalibrasi disimpan di `sumber/finish/`; tambahkan `--finish-ulang` untuk mengalibrasi ulang.
5. **Periksa dan render QC**:
   ```
   blender -b --python 99_SISTEM/pipeline/periksa_produk.py -- "02_PRODUK/<Kat>/<Nama>" [--tanpa-render]
   ```
   `PEMERIKSAAN.json` harus `lulus: true`. Skrip ini juga mengalibrasi Exposure studio agar luminans front hasil render sama dengan swatch finish default (dua iterasi render kecil), lalu menyimpannya ke root produk (`ns_exposure`) dan `INFORMASI.json` (`studio_exposure`); addon memakainya saat impor. Kalibrasi dan render QC memakai view transform **Khronos PBR Neutral** (bukan AgX, yang menekan saturasi kayu hangat sampai setengahnya sehingga oak terlihat pucat/pink); pilihan ini disimpan ke root (`ns_view_transform`, `ns_look`) dan `INFORMASI.json` (`studio_view`), addon memasangnya saat impor. Koreksi rona kecil (tint 0,6–1,6) disimpan di `ns_tint`. Render probe kalibrasi dipaksa PNG 8-bit: PNG 16-bit dimuat Blender sebagai float linear sehingga `Image.pixels` bukan sRGB (bug ini sempat membuat semua kalibrasi ±2 EV terlalu terang sampai 27 Okt 2026). Template studio kini netral (lampu putih, world abu, Khronos), jadi tint hasil kalibrasi seharusnya mendekati 1. **Sejak 28 Okt 2026 (studio berstandar, `scene['ns_std_exposure']`):** exposure tidak lagi dikalibrasi per produk; hanya tint kayu (0,4–1,8, ikut membawa terang) yang disamakan dengan swatch, dan `ns_exposure` lama dihapus dari root produk. Render QC di `04_HASIL_RENDER/<Nama_Folder>/qc/`: `hero.png`, `front.png`, `side.png`, `hero_laci_terbuka.png`, `front_ortho.png` (L × T), `side_ortho.png` (D × T), `finish_<id>.png` (HERO per finish) dan `finish_<id>_tekstur_vs_swatch.png`.
6. **Impor ke studio** lewat `MULAI_STUDIO.cmd` → Pilih file produk → pilih finish di kotak FINISH → render.

## Finish (mengikuti data produk)

Tidak ada katalog finish kayu global. Finish kayu sebuah produk didefinisikan di `produk.json` produk itu (`finish_kayu`), dibangun saat `bangun_produk.py`, dan ditanam di file produk. Yang global hanya **tekstur dasar** (set PBR seamless) dan **hardware** di `02_PRODUK/_FINISH/finishes.json`.

### Menambah tekstur dasar dari Poly Haven (lewat panel Blender)

1. Di https://polyhaven.com/textures/wood pilih veneer berserat lurus (mis. `silver_oak_veneer_01`, `ash_veneer`, `grey_oak_veneer_01`, `oak_veneer_02`). Unduh **Blend, 4K**; hasilnya zip berisi `.blend` + `textures/` (diff jpg, rough exr, nor_gl exr, disp, ao).
2. Di Blender: panel **Nakas Studio → Tekstur finish produk (Poly Haven) → Tambah tekstur dasar**, pilih zip-nya (atau folder hasil ekstrak). Addon menyalin diff/rough/normal ke `02_PRODUK/_FINISH/tekstur_dasar/<id>/`, mengubah EXR ke JPG, mendeteksi arah serat gambar, dan mendaftarkannya. Disp dan AO tidak dipakai.
3. Dengan produk aktif: pilih **Finish** (daftar finish produk itu) dan **Tekstur dasar**, klik **Pakai tekstur ini untuk finish** (dicatat di produk.json produk).
4. Klik **Bangun ulang produk aktif**. Blender membangun ulang file produk dan memeriksanya di latar (log `99_SISTEM/_kerja/bangun_produk.log`); centang "Render QC" bila ingin render ulang. Setelah selesai, impor ulang produk lewat "Pilih file produk".

Baris perintah yang setara: `blender -b --factory-startup --python 99_SISTEM/pipeline/daftar_tekstur_dasar.py -- <zip>` lalu `bangun_produk.py -- <produk.json> --finish-ulang` → `periksa_produk.py`.

- `tekstur_dasar.<id>.serat_gambar` (`V`/`H`) menentukan apakah Mapping diputar 90° agar serat selalu tegak di sisi produk; `ukuran_m` ukuran fisik satu tile (default 1 × 1 m).
- Swatch klien diambil langsung dari PDF (gambar tertanam, bukan tangkapan layar). `ekstrak_gambar_pdf.py <pdf> <folder>` menampilkan daftar gambar + nomor halaman untuk mengisi `sumber.obj` di produk.json.
- `finish_kayu.py` (modul): ekstraksi swatch, kalibrasi warna (serat dari luminans tekstur dasar, warna dari swatch, `gain_kontras`), node group `TALA Kayu`, material kayu/hardware. Hasil per finish di `sumber/finish/`.
- `buat_finish_library.py` (Blender): bangun `Finish_Library.blend` berisi node group + material `HW | …` saja.

## Catatan teknis

- STLOUT AutoCAD menulis koordinat dalam **UCS gambar yang tersimpan**, bukan WCS. Akibatnya (ditemukan pada Zuma Tallboy, 27 Okt 2026): sumbu tertukar, translasi pada sumbu tertentu dibuang (semua solid mulai dari 0), dan arah sumbu itu **terbalik per solid** sehingga bulatan tepi dan grip handle tercermin ke sisi belakang walau bounding box-nya benar. Karena itu `dwg_ke_stl.py` sekarang menjalankan `UCS World` sebelum STLOUT: STL = WCS persis (X lebar, Y kedalaman, Z tinggi), `sumbu` di produk.json tinggal menyatakan arah atas/depan model dalam WCS (Zuma Tallboy: `{"atas": "+Z", "depan": "-Y"}`). `periksa_produk.py` tetap membandingkan tiga ukuran luar yang diurutkan. Perhatian: accoreconsole menyimpan ulang DWG yang dibuka (membuat `.bak`), jadi selalu ekspor dari salinan di `sumber/`, bukan file asli.
- Cadangan bila UCS World tidak cukup: `dwg_ke_stl.py` menjalankan **MASSPROP** tiap solid (bounding box WCS, file `massprop_<i>.mpr`), menentukan pemetaan sumbu STL→WCS dari ukuran bbox, tanda sumbu dari urutan posisi atau, untuk sumbu yang translasinya hilang, dari pencocokan verteks dengan `semua_solid.stl` (bisa dipaksa `--tanda=1,1,-1`), lalu mencerminkan dan menggeser tiap STL ke posisi pasti. Tercatat di `parts.json` (`bbox_wcs`, `offset`, `tanda`) dan `dwg_info.json` (`sumbu_stl_ke_wcs`, `metode_tanda`). `min_cad` di produk.json hanya untuk kasus khusus. Produk yang diekspor sebelum perbaikan ini sebaiknya diekspor dan dibangun ulang bila ada detail asimetris (bulatan tepi, handle).
- Serat: `serat: "H"` membuat serat mendatar searah di semua muka part (muka tegak memakai sumbu datar bidangnya, muka atas memakai X). Dipakai untuk Zuma Bed atas permintaan pengguna.
- `Image.pixels` Blender memberi nilai byte/255 apa adanya (sRGB) untuk gambar 8-bit; skrip tekstur sengaja tidak mengonversi ke linear.
- Folder `99_SISTEM/pydeps` lama tidak bisa dibaca (ACL rusak) dan tidak dipakai lagi; semua skrip hanya memakai stdlib + numpy bawaan Blender.
- Setelah mengubah addon atau template, jalankan `blender -b 01_STUDIO/Studio_Nakas.blend --python 99_SISTEM/uji_paket.py` (lihat jumlah cek di hasil_pemeriksaan.json) dan salin addon ke `%APPDATA%\Blender Foundation\Blender\5.2\scripts\addons\`.

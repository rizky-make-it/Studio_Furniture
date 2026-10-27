# Standar produk untuk Studio Furniture (v2)

Simpan setiap produk dalam `02_PRODUK/<Kategori>/<Nama_Produk>/<Nama_Produk>.blend`, disertai `INFORMASI.json`. Folder `sumber/` di sampingnya menyimpan `produk.json`, hasil ekspor DWG, dan gambar referensi.

## Geometri

- File hanya berisi produk: mesh, material, root, pengontrol laci, dan driver yang dibutuhkan.
- Satu collection produk. Seluruh komponen berada di bawah satu root (empty) dengan properti `ns_product_root=True`.
- Satuan meter, `scale_length=1`. Dimensi sesuai ukuran nyata dari DWG; root menyimpan `dimensions_cm`.
- Depan menghadap −Y, lebar sepanjang X, tinggi sepanjang Z; bagian terbawah menyentuh Z=0.
- Tidak menyertakan ruangan, lampu, kamera studio, maupun addon.
- Laci: empty `DRAWER_n` dengan properti `ns_drawer=n` dan `Open (m)` (0 … travel). Driver `location.y = -Open (m)`. Semua bagian yang ikut bergerak (front, kotak laci, handle) menjadi anak empty ini.
- Detail yang dibuat: eksterior rapi, bevel tepi kecil, kotak laci sederhana (dasar, sisi, belakang). Rel, sekrup, dan hardware interior tidak dibuat.

## UV

- Satu UV map bernama `UV meter`, 1 satuan UV = 1 meter, dipetakan tri-planar.
- Sisi tegak: serat vertikal (V = tinggi). Permukaan atas: serat sepanjang X (lebar), kecuali `produk.json` menentukan lain untuk part tertentu.
- Material finish memakai Mapping dengan skala `1 / ukuran_tekstur_m`, jadi ukuran serat selalu benar secara fisik.

## Material per peran (bukan per finish)

Material pada mesh dinamai menurut **peran**, dan setiap material punya properti `ns_role`:

| Peran    | Nama material pada produk | Isi                               |
|----------|---------------------------|-----------------------------------|
| `WOOD_A` | `ROLE \| WOOD_A` atau finish default (`FIN \| …`) | Kayu utama: carcass, front, top |
| `WOOD_B` | `ROLE \| WOOD_B`          | Kayu sekunder: bagian dalam laci  |
| `HANDLE` | `ROLE \| HANDLE` atau `HW \| …` | Handle / pull                |
| `METAL`  | `ROLE \| METAL`           | Logam lain (kaki, bracket)        |
| `FELT`   | `ROLE \| FELT`            | Felt pad, bagian non-kayu matte   |

- **Finish kayu mengikuti data produk.** Semua finish kayu yang berlaku untuk produk itu (dari PDF/katalog klien atau foto sampel) didefinisikan di `sumber/produk.json` bagian `finish_kayu`, dibangun menjadi material `FIN | <nama>` (`ns_role=WOOD_A`, `ns_finish_id`, `ns_finish_nama`, `ns_finish_dasar`) dan **ditanam di file produk** dengan tekstur ter-pack. Satu di antaranya (`finish.default`) terpasang pada semua slot `WOOD_A`; sisanya tersimpan (fake user) dan dibawa ikut saat produk diimpor ke studio.
- Dropdown finish kayu di studio hanya menampilkan finish yang dibawa produk. Tidak ada katalog finish kayu global.
- Handle: satu material `HW | <nama>` default ter-embed; pilihan handle lain diambil dari `02_PRODUK/_FINISH/Finish_Library.blend` (library hanya berisi hardware + node group `TALA Kayu`).
- Root menyimpan `ns_finishes` (id finish yang dibawa), `ns_default_finish`, `ns_finish_handle`, dan `ns_spec` (path produk.json) agar panel studio bisa membangun ulang produk.
- Produk lama tanpa `ns_role` tetap dikenali: material dengan metallic ≥ 0,5 dianggap `HANDLE`, selebihnya `WOOD_A`; produk lama tidak punya pilihan finish.

## Tekstur dasar dan finish

- `02_PRODUK/_FINISH/finishes.json` hanya memuat `tekstur_dasar` (set PBR seamless, mis. unduhan Poly Haven, di `tekstur_dasar/<id>/`, dengan `serat_gambar` V/H dan `ukuran_m`) dan `hardware`.
- Tiap entri `finish_kayu` di produk.json berisi `id`, `nama`, `sumber` (`pdf`, `halaman`, `obj` gambar tertanam) **atau** `swatch` (file relatif ke `sumber/`), `tekstur_dasar`, `kilap`, `kalibrasi.gain_kontras`. `bangun_produk.py` mengekstrak swatch, mengalibrasi warna tekstur dasar ke swatch, dan menyimpan hasilnya di `sumber/finish/` (`<ID>_swatch.*`, `<ID>_albedo.jpg`, `<ID>_swatch_seamless.png`, `<ID>_statistik.json`).
- Material kayu memakai node group `TALA Kayu` (albedo terkalibrasi + normal + kekasaran; opsi "Pakai swatch asli" untuk tampilan persis foto klien).
- Render QC per finish: `04_HASIL_RENDER/<Produk>/qc/finish_<id>.png` dan `finish_<id>_tekstur_vs_swatch.png`.

## Metadata (`INFORMASI.json`)

Memuat `id`, `category`, `name`, `dimensions_cm`, `front`, `textures`, `source_geometry`, `unit_assumption`, `drawers`, `finishes` (daftar id, nama, tekstur dasar, warna rata-rata swatch), `default_finish`, `default_handle`, dan catatan referensi.

Preset lighting kategori dibuat terpisah dari aset produk. Saat ini hanya Nakas tersedia; produk kategori lain membutuhkan preset tersendiri sebelum pencahayaan dan framingnya dianggap siap.

Impor melalui panel menggunakan append, mempertahankan hierarchy, material, dan driver; sumber produk tidak berubah. Setelah impor, studio menempatkan model di tengah lantai dan menyesuaikan kamera. Periksa ukuran serta komposisi detail.

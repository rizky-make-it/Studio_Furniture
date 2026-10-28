# Studio Katalog Doheny — cara pakai

Tujuannya, semua foto katalog Doheny punya latar, cahaya, sudut, rasio dan warna kayu yang sama, berapa pun ukuran produknya.

## File
| File | Lokasi |
|---|---|
| Studio_Katalog_Doheny.blend (studio master, jangan diubah) | 01_STUDIO |
| katalog_doheny.py (mesin render) | 99_SISTEM |
| RENDER_KATALOG_DOHENY.cmd / UJI_CEPAT_KATALOG_DOHENY.cmd | 99_SISTEM |
| Tekstur finish standar (natural oak, oak madu) | 02_PRODUK\_FINISH\katalog_doheny |
| Hasil render | 04_HASIL_RENDER\Katalog_Doheny\<Produk> |

## Cara render
1. Seret file produk .blend (misalnya `02_PRODUK\Nakas\Doheny_Bed\Doheny_Bed.blend`) ke **UJI_CEPAT_KATALOG_DOHENY.cmd**. Ini menghasilkan pratinjau kecil dalam beberapa menit, untuk cek framing.
2. Kalau sudah oke, seret file yang sama ke **RENDER_KATALOG_DOHENY.cmd**. Hasilnya 4 foto 2000×2500 (4:5) di 256 sampel. Bisa juga beberapa file sekaligus.

Hasil yang keluar: `Doheny_<Produk>_HERO.png`, `_FRONT`, `_SIDE`, `_LIFESTYLE`, plus `QC_katalog.json`.

## Yang dikunci (sama untuk semua produk)
- **Latar:** putih hangat. Lantai menyatu ke dinding belakang, dengan dinding kiri untuk sudut ruang.
- **Cahaya:** key sun dari kanan-depan dan fill lembut. Karena cahaya matahari tidak bergantung jarak, kecerahan sama untuk meja kecil maupun ranjang.
- **Warna:** Khronos PBR Neutral, eksposur −2,5 (standar studio netral).
- **Sudut:**
  - HERO: 3/4 kanan depan
  - FRONT: tegak lurus
  - SIDE: samping kanan
  - LIFESTYLE: dekat, terpotong
- **Framing:** produk otomatis ditaruh di lantai dan dipusatkan. Kamera menyesuaikan ukuran produk dengan margin yang sama.
- **Finish kayu:** `--finish natural_oak` (bawaan .cmd) mengganti kayu produk ke Doheny Natural Oak standar. Pilihan lain: `oak_madu`. Untuk memakai finish asli dari file produk, hapus `--finish %FINISH%` di .cmd.

## Syarat file produk
- Isinya hanya produk: tanpa studio, kamera atau lampu. Objek studio yang terbawa otomatis ditolak, tapi lebih aman bersih.
- Material kayu diberi nama berawalan `FIN |` atau properti `ns_role = WOOD_A`, supaya finish standar bisa dipasang.

## QC
`QC_katalog.json` mencatat kecerahan (L*) lantai bawah dan dinding atas. Untuk HERO dan FRONT, nilai normalnya sekitar lantai 90 dan dinding 87–88. Kalau angkanya jauh berbeda, ada yang berubah di studio.

## Opsi lanjutan (baris perintah)
`blender -b 01_STUDIO\Studio_Katalog_Doheny.blend --python 99_SISTEM\katalog_doheny.py -- <produk.blend> [--finish natural_oak|oak_madu] [--uji] [--nama NamaProduk] [--keluar folder] [--simpan-sesi]`

`--simpan-sesi` menyimpan file .blend sesi render, kalau ingin mengatur ulang manual.

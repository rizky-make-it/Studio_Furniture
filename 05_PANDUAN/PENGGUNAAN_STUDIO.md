# Penggunaan studio

Mulai dari `MULAI_STUDIO.cmd` di folder utama, atau shortcut **Studio Furniture** di Desktop. File ini membuka template studio kosong dan menyimpannya sebagai sesi baru di `03_PROYEK`.

## Memasukkan produk

Di panel **Nakas Studio → MULAI DARI SINI**, pilih **Muat contoh nakas**, atau **Pilih file produk**. Pemilih file langsung menuju folder `02_PRODUK`. Posisi model dan framing kamera diatur otomatis setelah impor; periksa dimensi nyata dan komposisi kamera detail.

Contoh: `02_PRODUK/Nakas/Nakas_Oak_2Laci.blend`. Produk baru akan ditempatkan di folder kategori yang sesuai, mengikuti `STANDAR_FILE_PRODUK.md`.

Impor menyalin geometri dan material ke sesi. Sumber di `02_PRODUK` tetap terpisah. Perubahan sumber tidak memperbarui sesi lama secara otomatis.

## Mengganti finish

Setelah produk dimuat, kotak **FINISH** muncul di bawah "MULAI DARI SINI". Pilih **Finish kayu** dan **Finish handle** dari dropdown; semua bagian dengan peran yang sama langsung berganti. Finish kayu yang ditawarkan adalah finish yang dibawa produk itu sendiri (ditentukan di `sumber/produk.json` produk, sesuai data klien), jadi tiap produk punya daftar finish sendiri. Pilihan handle tambahan diambil dari `02_PRODUK/_FINISH/Finish_Library.blend`. Sesi tetap mandiri saat dipindahkan, dan file produk sumber tidak berubah. Tombol ↻ di samping dropdown memasang ulang finish yang dipilih. Ctrl+Z membatalkan.

Render tiap finish produk ada di `04_HASIL_RENDER/<Produk>/qc/finish_<id>.png`, dan perbandingan tekstur dengan swatch klien di `finish_<id>_tekstur_vs_swatch.png`.

## Tampilan dan lampu

- **Cepat**: perkiraan lighting yang ringan. Mesh perlengkapan studio disembunyikan hanya dalam viewport produk agar tidak menutupi sumber cahaya EEVEE.
- **Cek detail**: Cycles dengan 8 preview samples. Gunakan untuk menilai lighting lebih akurat sebelum render.
- **Jeda**: tampilan bentuk tanpa perhitungan lighting.
- **Ruang studio**: inspeksi peralatan. Dalam mode Cepat, tampilan ini memakai Solid.
- Tombol angle, putar, zoom, dan kembali ke kamera dapat diklik langsung. Tidak memerlukan shortcut dengan kursor di viewport.

Key adalah cahaya utama; Fill membuka bayangan; Rim menegaskan tepi; Top menerangi permukaan atas; Tengah (softbox rendah tepat di depan rongga) menerangi bagian tengah/rongga rak agar tidak gelap; pakai secukupnya agar bentuk dari Key tidak hilang. Lampu Tengah dipasang/diperbarui oleh `99_SISTEM/tambah_lampu_tengah.py`. Sejak 28 Okt 2026 semua angle memakai **satu profil watt (V3)**: Key 238 · Fill 64,6 · Rim 170 · Top 76,5 · Tengah 24 W, sehingga terang dan kontras antar-angle sama. Setiap angle tetap bisa diatur terpisah bila perlu. **Reset watt angle** memulihkan angle aktif; **Reset watt kategori** memulihkan seluruh angle kategori. Exposure tidak ikut direset; standar template sejak 27 Okt 2026 adalah **-2,50** (dikalibrasi dengan kartu abu 18%).

Saat produk diimpor, rig lampu otomatis diperbesar mengikuti ukuran produk (label "skala rig" di panel): lampu digeser menjauh dan watt dinaikkan kuadratnya sehingga produk besar seperti tallboy mendapat pencahayaan setara nakas. Reset watt memperhitungkan skala ini. Exposure dan view transform **tidak lagi mengikuti produk**: setiap impor memasang standar studio (exposure -2,50, Khronos PBR Neutral) supaya semua produk terender dengan terang yang sama. Kesesuaian warna kayu dengan swatch diatur di material produk (tint hasil `periksa_produk.py`), bukan lewat exposure.

### Studio netral (27 Okt 2026)
Agar warna kayu di render sama dengan swatch/foto referensi, template dibuat **netral warna**: semua lampu putih (1, 1, 1), world abu netral 0,5, view transform **Khronos PBR Neutral** tanpa look, exposure -2,50. Sebelumnya Key hangat dan Fill kebiruan, world biru, AgX Medium High Contrast dan exposure -0,30: kombinasi itu menggeser rona, memotong saturasi oak dari 0,50 ke 0,39, dan membuat kartu abu 18% terender hampir putih (kelebihan ±2,5 EV). Dengan studio netral, mengubah watt atau exposure hanya mengubah terang, tidak mengubah rona. **Jangan memberi warna pada lampu** untuk "menghangatkan" kayu; kalau rona kayu harus berubah, ubah finish produknya, bukan lampunya. Cek kapan saja dengan `99_SISTEM/uji_warna_studio.py` (kartu warna; hasil benar bila dHue ≈ 0 dan saturasi tidak turun).

Buka `PANDUAN_LAMPU.html` untuk foto berlabel dan denah lampu.

## Menyimpan dan melanjutkan

Tekan Ctrl+S untuk menyimpan sesi. Untuk memberi nama, klik **Simpan proyek sebagai...**, pilih lokasi di `03_PROYEK`. Jangan menyimpan sesi ke dalam `01_STUDIO` atau menimpa file sumber di `02_PRODUK`.

Untuk melanjutkan, buka **BUKA_PROYEK_TERSIMPAN.cmd** lalu pilih file sesi. Pembuka ini memuat panel dari paket, termasuk jika addon belum dipasang di komputer lain.

## Render

Folder output disiapkan di `04_HASIL_RENDER/<nama_sesi>/`. Pilih kualitas, centang angle, lalu gunakan render batch. Setiap batch membuat subfolder baru. **Render angle aktif** menampilkan hasil di jendela render; simpan gambarnya secara manual jika perlu. Gunakan batch untuk penulisan PNG otomatis.

Saat ini hanya preset kategori Nakas tersedia. Produk kategori lain membutuhkan preset tersendiri sebelum pencahayaan dan framingnya dapat dianggap siap.

## Memindahkan paket

Salin seluruh folder **Studio_Furniture**. Tekstur produk sudah packed. Pembuka mencari Blender 5.2 pada instalasi standar atau `blender.exe` di PATH; lokasi lain dapat diatur di `99_SISTEM/buka_studio.ps1`.


## Latar konsisten (sejak 28 Okt 2026)

Latar semua render dikunci **abu terang netral** (atas #E8E7E5 → bawah #DFDEDC, rata-rata ±#E4E3E1), sama persis untuk setiap produk dan angle:

- Cyclorama dijadikan **shadow catcher**: hanya bayangan produk yang tampil, bukan gradasi cahaya lampu yang berubah-ubah mengikuti ukuran produk.
- Film transparan; warna latar ditempel di compositor (node group `NS | Latar`). Node *Netralkan exposure* diberi driver `-exposure`, jadi menggeser Exposure di panel hanya mengubah terang produk, warna latar tetap.
- Untuk melihat latar di viewport, pratinjau memakai *Viewport Compositor* (otomatis oleh addon).
- Dinding, balok plafon, dan perlengkapan tidak terlihat kamera dan tidak meninggalkan bayangan di latar.
- Mengganti warna latar: ubah `LATAR_HEX` di `99_SISTEM/pasang_latar_studio.py`, lalu jalankan `blender -b --python 99_SISTEM/pasang_latar_studio.py -- apply` (warna dikalibrasi otomatis lewat render). `-- check` merender semua produk berdampingan ke `04_HASIL_RENDER/_LAMPU_CHECK/latar/lembar_kontak_hero.png` tanpa menyimpan template.
- Backup template sebelum perubahan: `01_STUDIO/Studio_Nakas_sebelum_latar_20261028_1428.blend`. Sesi lama di `03_PROYEK` masih memakai latar lama; buat sesi baru lewat MULAI_STUDIO untuk memakai latar ini.

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

Key adalah cahaya utama; Fill membuka bayangan; Rim menegaskan tepi; Top menerangi permukaan atas; Tengah (softbox rendah tepat di depan rongga) menerangi bagian tengah/rongga rak agar tidak gelap; pakai secukupnya agar bentuk dari Key tidak hilang. Lampu Tengah dipasang/diperbarui oleh `99_SISTEM/tambah_lampu_tengah.py`. Setiap angle menyimpan watt terpisah. **Reset watt angle** memulihkan angle aktif; **Reset watt kategori** memulihkan seluruh angle kategori. Exposure tidak ikut direset; standar Nakas adalah -0,30.

Saat produk diimpor, rig lampu otomatis diperbesar mengikuti ukuran produk (label "skala rig" di panel): lampu digeser menjauh dan watt dinaikkan kuadratnya sehingga produk besar seperti tallboy mendapat pencahayaan setara nakas. Reset watt memperhitungkan skala ini. Exposure juga diatur otomatis ke nilai `studio_exposure` hasil kalibrasi produk (terang front disamakan dengan swatch referensi); ubah bebas bila perlu.

Buka `PANDUAN_LAMPU.html` untuk foto berlabel dan denah lampu.

## Menyimpan dan melanjutkan

Tekan Ctrl+S untuk menyimpan sesi. Untuk memberi nama, klik **Simpan proyek sebagai...**, pilih lokasi di `03_PROYEK`. Jangan menyimpan sesi ke dalam `01_STUDIO` atau menimpa file sumber di `02_PRODUK`.

Untuk melanjutkan, buka **BUKA_PROYEK_TERSIMPAN.cmd** lalu pilih file sesi. Pembuka ini memuat panel dari paket, termasuk jika addon belum dipasang di komputer lain.

## Render

Folder output disiapkan di `04_HASIL_RENDER/<nama_sesi>/`. Pilih kualitas, centang angle, lalu gunakan render batch. Setiap batch membuat subfolder baru. **Render angle aktif** menampilkan hasil di jendela render; simpan gambarnya secara manual jika perlu. Gunakan batch untuk penulisan PNG otomatis.

Saat ini hanya preset kategori Nakas tersedia. Produk kategori lain membutuhkan preset tersendiri sebelum pencahayaan dan framingnya dapat dianggap siap.

## Memindahkan paket

Salin seluruh folder **Studio_Furniture**. Tekstur produk sudah packed. Pembuka mencari Blender 5.2 pada instalasi standar atau `blender.exe` di PATH; lokasi lain dapat diatur di `99_SISTEM/buka_studio.ps1`.

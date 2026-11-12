<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Indonesian translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../id-ID.php; the frontend strings live in ../app/id-ID.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Instal toolchain dan jalankan aplikasi sebagai layanan, tanpa Docker.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Build dan jalankan aplikasi Go, Rust, Bun, Java, .NET, Python, Ruby, PHP, atau aplikasi yang sudah dikompilasi di domain ini.',
    'permissionName' => 'Manajemen aplikasi Runway',
    'permissionDescription' => 'Mengizinkan pelanggan untuk mem-build dan menjalankan aplikasi sebagai layanan latar belakang dengan Runway.',

    // Errors
    'errorHelperFailed' => 'Helper dengan hak istimewa gagal: %%details%%',
    'errorAccessDenied' => 'Akses ditolak.',
    'errorNoDomain' => 'Domain tidak ditemukan.',
    'errorNoHosting' => 'Domain ini tidak memiliki hosting web.',
    'errorNotConfigured' => 'Aplikasi belum dikonfigurasi. Simpan pengaturan terlebih dahulu.',
    'errorInvalidOperation' => 'Operasi tidak valid.',
    'errorInvalidValue' => 'Nilai tidak valid.',
    'errorPostRequired' => 'Tindakan ini memerlukan permintaan POST.',
    'errorInternal' => 'Terjadi kesalahan internal. Detailnya ada di log panel Plesk.',
    'errorRuntime' => 'Pilih runtime yang valid.',
    'errorToolchain' => 'Pilih versi toolchain yang valid.',
    'errorAppRoot' => 'Root aplikasi harus berupa jalur di dalam langganan (huruf, angka, dan . _ - @ + /), tanpa segmen "." atau "..".',
    'errorBuildCmd' => 'Perintah build terlalu panjang atau mengandung karakter kontrol.',
    'errorStartCmd' => 'Perintah start harus berupa satu baris tanpa karakter kontrol (maks. 1000 karakter).',
    'errorStartCmdEmpty' => 'Perintah start diperlukan untuk mengaktifkan aplikasi.',
    'errorLimit' => '%%name%% harus berupa bilangan bulat dalam rentang yang diizinkan.',
    'errorEnvLine' => 'Baris %%line%%: gunakan format KUNCI=nilai.',
    'errorEnvKey' => 'Baris %%line%%: "%%key%%" bukan nama variabel yang valid.',
    'errorEnvReserved' => '%%key%% dikelola oleh Runway dan tidak dapat diatur.',
    'errorEnvLoader' => '%%key%% tidak dapat diatur di sini; letakkan di perintah start (mis. %%key%%=... ./app).',
    'errorEnvValue' => 'Nilai %%key%% tidak boleh mengandung karakter ganti baris atau karakter kontrol.',
    'errorEnvTooMany' => 'Terlalu banyak variabel lingkungan (maksimum 200).',
    'errorListen' => 'Pilih mode mendengarkan yang valid.',
    'errorMode' => 'Pilih mode aplikasi yang valid.',
    'errorMountPath' => 'Jalur URL harus berupa jalur seperti /api (huruf, angka, dan . _ ~ -).',
    'errorStaticPaths' => 'Jalur statis harus berupa daftar jalur URL.',
    'errorStaticPath' => '"%%path%%" bukan jalur URL yang valid (contoh: /assets).',
    'errorStaticPathsTooMany' => 'Maksimal %%max%% jalur statis yang diizinkan.',
    'errorStaticPathsTooLong' => 'Total panjang jalur statis terlalu besar (maksimal %%max%% karakter).',
    'errorConfigTooLarge' => 'Total panjang pengaturan terlalu besar (%%length%% dari maksimal %%max%% karakter): persingkat perintah atau jalurnya.',
    'errorHealthPath' => 'Jalur pemeriksaan kesehatan harus berupa jalur URL seperti /healthz.',
    'errorPortRange' => 'Port pertama tidak boleh lebih besar dari port terakhir.',
    'errorSettingRange' => 'Masukkan bilangan bulat antara %%min%% dan %%max%%.',
    'errorListenMode' => 'Worker latar belakang tidak memiliki listener: pilih "Tidak ada" sebagai mode mendengarkan, atau mode web dengan port TCP atau soket Unix.',
    'errorMountPathReserved' => '%%path%% digunakan oleh Plesk (statistik web atau validasi sertifikat) dan tidak dapat diteruskan melalui proxy.',
    'errorMaxApps' => 'Langganan ini sudah mencapai jumlah maksimum aplikasi aktif (%%max%%).',
    'errorFetchUrl' => 'Masukkan URL https:// (maks. 2048 karakter, tanpa spasi).',
    'errorFetchHttps' => 'Hanya URL https:// yang dapat diunduh.',
    'errorSampleNotEmpty' => 'Root aplikasi tidak kosong. Konfirmasi bahwa aplikasi contoh boleh menimpa file. %%details%%',
    'errorSampleUnix' => 'Server PHP default (php -S) tidak dapat mendengarkan di soket Unix: instal toolchain FrankenPHP atau pilih TCP.',
    'errorFetchSha256' => 'Checksum SHA-256 harus terdiri dari 64 karakter heksadesimal.',
    'errorFetchFilename' => 'Nama file hanya boleh berisi huruf, angka, dan . _ + - (maks. 128 karakter).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Batas memori (MiB)',
    'fieldCpuPercent' => 'Batas CPU (%)',
    'fieldTasks' => 'Batas proses / thread',

    // Messages
    'messageSavedEnabled' => 'Pengaturan telah disimpan dan aplikasi sedang dimulai (ulang).',
    'messageSavedBuilding' => 'Pengaturan telah disimpan. Aplikasi sedang di-build dan akan dimulai (ulang) jika build berhasil; pantau di log "Build & deploy".',
    'messageSavedBuildNotStarted' => 'Pengaturan telah disimpan, tetapi build tidak dapat dimulai: %%details%%',
    'messageSavedDisabled' => 'Pengaturan telah disimpan. Aplikasi dinonaktifkan.',
    'messageAction_start' => 'Aplikasi sedang dimulai.',
    'messageAction_stop' => 'Aplikasi telah dihentikan. Aplikasi tetap berhenti sampai Anda memulainya lagi.',
    'messageAction_restart' => 'Aplikasi sedang dimulai ulang.',
    'messageDeployStarted' => 'Build telah dimulai. Pantau di log "Build & deploy".',
    'messageRemoved' => 'Aplikasi telah dihapus.',
    'messageJobStarted' => 'Tugas telah dimulai. Progresnya ditampilkan di bawah.',
    'messageToolchainRemoved' => '%%version%% telah dihapus.',
    'messageSampleWritten' => 'Aplikasi contoh telah ditulis (%%count%% file) dan pengaturan diperbarui.',
    'messageSampleWrittenOne' => 'Aplikasi contoh telah ditulis (satu file) dan pengaturan diperbarui.',
    'messageFetchStarted' => 'Unduhan telah dimulai. Pantau di log "Build & deploy".',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Menampilkan daftar aplikasi yang dikonfigurasi beserta statusnya.',
    'cli.commands.status' => 'Menampilkan status aplikasi suatu domain: --status <domain>',
    'cli.commands.start' => 'Memulai aplikasi suatu domain: --start <domain>',
    'cli.commands.stop' => 'Menghentikan aplikasi suatu domain; aplikasi tetap berhenti (termasuk setelah reboot atau deployment) hingga --start atau --restart: --stop <domain>',
    'cli.commands.restart' => 'Memulai ulang aplikasi suatu domain: --restart <domain>',
    'cli.commands.deploy' => 'Mem-build dan memulai ulang aplikasi suatu domain lalu menunggu hasilnya (aplikasi yang dihentikan akan di-build tetapi tetap berhenti): --deploy <domain> [-no-wait]',
    'cli.commands.enable' => 'Mengaktifkan aplikasi yang dikonfigurasi pada suatu domain: --enable <domain>',
    'cli.commands.disable' => 'Menonaktifkan aplikasi suatu domain: --disable <domain>',
    'cli.commands.toolchains' => 'Menampilkan daftar toolchain yang terinstal dan domain yang menggunakannya.',
    'cli.commands.install-toolchain' => 'Menginstal toolchain dan menunggu hasilnya: --install-toolchain <runtime> <versi> [-no-wait]',
    'cli.commands.reconcile' => 'Menyelaraskan layanan aplikasi dengan Plesk (domain yang dihapus, diganti namanya, atau ditangguhkan).',
];

<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Malay translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../ms-MY.php; the frontend strings live in ../app/ms-MY.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Pasang rantaian alat dan jalankan aplikasi sebagai perkhidmatan, tanpa Docker.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Bina dan jalankan aplikasi Go, Rust, Bun, Java, .NET, Python, Ruby, PHP atau prabina pada domain ini.',
    'permissionName' => 'Pengurusan aplikasi Runway',
    'permissionDescription' => 'Membenarkan pelanggan membina dan menjalankan aplikasi sebagai perkhidmatan latar belakang dengan Runway.',

    // Errors
    'errorHelperFailed' => 'Pembantu berkeistimewaan gagal: %%details%%',
    'errorAccessDenied' => 'Akses ditolak.',
    'errorNoDomain' => 'Domain tidak ditemui.',
    'errorNoHosting' => 'Domain ini tidak mempunyai pengehosan web.',
    'errorNotConfigured' => 'Aplikasi belum dikonfigurasi. Simpan tetapan dahulu.',
    'errorInvalidOperation' => 'Operasi tidak sah.',
    'errorInvalidValue' => 'Nilai tidak sah.',
    'errorPostRequired' => 'Tindakan ini memerlukan permintaan POST.',
    'errorInternal' => 'Ralat dalaman telah berlaku. Butirannya ada dalam log panel Plesk.',
    'errorRuntime' => 'Pilih masa jalan yang sah.',
    'errorToolchain' => 'Pilih versi rantaian alat yang sah.',
    'errorAppRoot' => 'Akar aplikasi mestilah laluan di dalam langganan (huruf, digit dan . _ - @ + /), tanpa segmen "." atau "..".',
    'errorBuildCmd' => 'Perintah bina terlalu panjang atau mengandungi aksara kawalan.',
    'errorStartCmd' => 'Perintah mula mestilah satu baris tanpa aksara kawalan (maks. 1000 aksara).',
    'errorStartCmdEmpty' => 'Perintah mula diperlukan untuk mendayakan aplikasi.',
    'errorLimit' => '%%name%% mestilah nombor bulat dalam julat yang dibenarkan.',
    'errorEnvLine' => 'Baris %%line%%: gunakan format KUNCI=nilai.',
    'errorEnvKey' => 'Baris %%line%%: "%%key%%" bukan nama pembolehubah yang sah.',
    'errorEnvReserved' => '%%key%% diuruskan oleh Runway dan tidak boleh ditetapkan.',
    'errorEnvLoader' => '%%key%% tidak boleh ditetapkan di sini; letakkannya dalam perintah mula (cth. %%key%%=... ./app).',
    'errorEnvValue' => 'Nilai %%key%% tidak boleh mengandungi pemisah baris atau aksara kawalan.',
    'errorEnvTooMany' => 'Terlalu banyak pembolehubah persekitaran (maksimum 200).',
    'errorListen' => 'Pilih mod dengar yang sah.',
    'errorMode' => 'Pilih mod aplikasi yang sah.',
    'errorMountPath' => 'Laluan URL mestilah laluan seperti /api (huruf, digit dan . _ ~ -).',
    'errorStaticPaths' => 'Laluan statik mestilah senarai laluan URL.',
    'errorStaticPath' => '"%%path%%" bukan laluan URL yang sah (contoh: /assets).',
    'errorStaticPathsTooMany' => 'Paling banyak %%max%% laluan statik dibenarkan.',
    'errorStaticPathsTooLong' => 'Laluan statik terlalu panjang secara keseluruhan (paling banyak %%max%% aksara).',
    'errorConfigTooLarge' => 'Tetapan terlalu panjang secara keseluruhan (%%length%% aksara, maksimum %%max%%): pendekkan perintah atau laluan.',
    'errorHealthPath' => 'Laluan semakan kesihatan mestilah laluan URL seperti /healthz.',
    'errorPortRange' => 'Port pertama tidak boleh lebih besar daripada port terakhir.',
    'errorSettingRange' => 'Masukkan nombor bulat antara %%min%% dan %%max%%.',
    'errorListenMode' => 'Pekerja latar belakang tidak mempunyai pendengar: pilih "Tiada" sebagai mod dengar, atau mod web dengan port TCP atau soket Unix.',
    'errorMountPathReserved' => '%%path%% digunakan oleh Plesk (statistik web atau pengesahan sijil) dan tidak boleh diproksikan.',
    'errorMaxApps' => 'Langganan ini sudah mencapai bilangan maksimum aplikasi yang didayakan (%%max%%).',
    'errorFetchUrl' => 'Masukkan URL https:// (maks. 2048 aksara, tanpa ruang).',
    'errorFetchHttps' => 'Hanya URL https:// boleh dimuat turun.',
    'errorSampleNotEmpty' => 'Akar aplikasi tidak kosong. Sahkan bahawa aplikasi contoh boleh menulis ganti fail. %%details%%',
    'errorSampleUnix' => 'Pelayan PHP lalai (php -S) tidak dapat mendengar pada soket Unix: pasang rantaian alat FrankenPHP atau pilih TCP.',
    'errorFetchSha256' => 'Jumlah semak SHA-256 mestilah 64 aksara heksadesimal.',
    'errorFetchFilename' => 'Nama fail hanya boleh mengandungi huruf, digit dan . _ + - (maks. 128 aksara).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Had memori (MiB)',
    'fieldCpuPercent' => 'Had CPU (%)',
    'fieldTasks' => 'Had proses / bebenang',

    // Messages
    'messageSavedEnabled' => 'Tetapan telah disimpan dan aplikasi sedang dimulakan (semula).',
    'messageSavedBuilding' => 'Tetapan telah disimpan. Aplikasi sedang dibina dan akan dimulakan (semula) apabila binaan berjaya; pantau kemajuannya dalam log "Bina & sebar".',
    'messageSavedBuildNotStarted' => 'Tetapan telah disimpan, tetapi binaan tidak dapat dimulakan: %%details%%',
    'messageSavedDisabled' => 'Tetapan telah disimpan. Aplikasi dinyahdayakan.',
    'messageAction_start' => 'Aplikasi sedang dimulakan.',
    'messageAction_stop' => 'Aplikasi telah dihentikan. Ia kekal dihentikan sehingga anda memulakannya semula.',
    'messageAction_restart' => 'Aplikasi sedang dimulakan semula.',
    'messageDeployStarted' => 'Binaan telah bermula. Pantau kemajuannya dalam log "Bina & sebar".',
    'messageRemoved' => 'Aplikasi telah dialih keluar.',
    'messageJobStarted' => 'Kerja telah bermula. Kemajuannya ditunjukkan di bawah.',
    'messageToolchainRemoved' => '%%version%% telah dialih keluar.',
    'messageSampleWritten' => 'Aplikasi contoh telah ditulis (%%count%% fail) dan tetapan telah dikemas kini.',
    'messageSampleWrittenOne' => 'Aplikasi contoh telah ditulis (satu fail) dan tetapan telah dikemas kini.',
    'messageFetchStarted' => 'Muat turun telah bermula. Pantau kemajuannya dalam log "Bina & sebar".',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Menyenaraikan aplikasi yang dikonfigurasi dan keadaannya.',
    'cli.commands.status' => 'Menunjukkan keadaan aplikasi sesuatu domain: --status <domain>',
    'cli.commands.start' => 'Memulakan aplikasi sesuatu domain: --start <domain>',
    'cli.commands.stop' => 'Menghentikan aplikasi sesuatu domain; ia kekal dihentikan (juga selepas but semula atau penyebaran) sehingga --start atau --restart: --stop <domain>',
    'cli.commands.restart' => 'Memulakan semula aplikasi sesuatu domain: --restart <domain>',
    'cli.commands.deploy' => 'Membina dan memulakan semula aplikasi sesuatu domain dan menunggu keputusannya (aplikasi yang dihentikan dibina tetapi kekal dihentikan): --deploy <domain> [-no-wait]',
    'cli.commands.enable' => 'Mendayakan aplikasi yang dikonfigurasi bagi sesuatu domain: --enable <domain>',
    'cli.commands.disable' => 'Menyahdayakan aplikasi sesuatu domain: --disable <domain>',
    'cli.commands.toolchains' => 'Menyenaraikan rantaian alat yang dipasang dan domain yang menggunakannya.',
    'cli.commands.install-toolchain' => 'Memasang rantaian alat dan menunggu keputusannya: --install-toolchain <masa-jalan> <versi> [-no-wait]',
    'cli.commands.reconcile' => 'Menyelaraskan perkhidmatan aplikasi dengan Plesk (domain yang dipadam, dinamakan semula atau digantung).',
];

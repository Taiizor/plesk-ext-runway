<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Vietnamese translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../vi-VN.php; the frontend strings live in ../app/vi-VN.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Cài đặt bộ công cụ và chạy ứng dụng dưới dạng dịch vụ, không cần Docker.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Biên dịch và chạy ứng dụng Go, Rust, Bun, Java, .NET, Python, Ruby, PHP hoặc ứng dụng dựng sẵn trên tên miền này.',
    'permissionName' => 'Quản lý ứng dụng Runway',
    'permissionDescription' => 'Cho phép khách hàng biên dịch và chạy ứng dụng dưới dạng dịch vụ nền bằng Runway.',

    // Errors
    'errorHelperFailed' => 'Trình trợ giúp đặc quyền gặp lỗi: %%details%%',
    'errorAccessDenied' => 'Truy cập bị từ chối.',
    'errorNoDomain' => 'Không tìm thấy tên miền.',
    'errorNoHosting' => 'Tên miền này không có dịch vụ lưu trữ web.',
    'errorNotConfigured' => 'Ứng dụng chưa được cấu hình. Hãy lưu cài đặt trước.',
    'errorInvalidOperation' => 'Thao tác không hợp lệ.',
    'errorInvalidValue' => 'Giá trị không hợp lệ.',
    'errorPostRequired' => 'Hành động này cần được gửi bằng yêu cầu POST.',
    'errorInternal' => 'Đã xảy ra lỗi nội bộ. Chi tiết có trong nhật ký bảng điều khiển Plesk.',
    'errorRuntime' => 'Hãy chọn một môi trường chạy hợp lệ.',
    'errorToolchain' => 'Hãy chọn một phiên bản bộ công cụ hợp lệ.',
    'errorAppRoot' => 'Thư mục gốc ứng dụng phải là một đường dẫn bên trong thuê bao (chữ cái, chữ số và . _ - @ + /), không chứa phân đoạn "." hoặc "..".',
    'errorBuildCmd' => 'Lệnh biên dịch quá dài hoặc chứa ký tự điều khiển.',
    'errorStartCmd' => 'Lệnh khởi động phải là một dòng duy nhất không chứa ký tự điều khiển (tối đa 1000 ký tự).',
    'errorStartCmdEmpty' => 'Cần có lệnh khởi động để bật ứng dụng.',
    'errorLimit' => '%%name%% phải là một số nguyên trong phạm vi cho phép.',
    'errorEnvLine' => 'Dòng %%line%%: hãy dùng định dạng BIẾN=giá trị.',
    'errorEnvKey' => 'Dòng %%line%%: "%%key%%" không phải là tên biến hợp lệ.',
    'errorEnvReserved' => '%%key%% do Runway quản lý và không thể đặt được.',
    'errorEnvLoader' => 'Không thể đặt %%key%% ở đây; hãy đưa nó vào lệnh khởi động (ví dụ: %%key%%=... ./app).',
    'errorEnvValue' => 'Giá trị của %%key%% không được chứa ký tự xuống dòng hoặc ký tự điều khiển.',
    'errorEnvTooMany' => 'Quá nhiều biến môi trường (tối đa 200).',
    'errorListen' => 'Hãy chọn một chế độ lắng nghe hợp lệ.',
    'errorMode' => 'Hãy chọn một chế độ ứng dụng hợp lệ.',
    'errorMountPath' => 'Đường dẫn URL phải có dạng như /api (chữ cái, chữ số và . _ ~ -).',
    'errorStaticPaths' => 'Đường dẫn tĩnh phải là một danh sách các đường dẫn URL.',
    'errorStaticPath' => '"%%path%%" không phải là đường dẫn URL hợp lệ (ví dụ: /assets).',
    'errorStaticPathsTooMany' => 'Chỉ được phép tối đa %%max%% đường dẫn tĩnh.',
    'errorStaticPathsTooLong' => 'Tổng độ dài các đường dẫn tĩnh quá lớn (tối đa %%max%% ký tự).',
    'errorConfigTooLarge' => 'Tổng độ dài cài đặt quá lớn (%%length%% ký tự, tối đa %%max%%): hãy rút ngắn các lệnh hoặc đường dẫn.',
    'errorHealthPath' => 'Đường dẫn kiểm tra tình trạng phải là một đường dẫn URL như /healthz.',
    'errorPortRange' => 'Cổng đầu tiên không được lớn hơn cổng cuối cùng.',
    'errorSettingRange' => 'Hãy nhập một số nguyên từ %%min%% đến %%max%%.',
    'errorListenMode' => 'Tiến trình nền không có trình lắng nghe: hãy chọn "Không" làm chế độ lắng nghe, hoặc một chế độ web với cổng TCP hoặc socket Unix.',
    'errorMountPathReserved' => '%%path%% được Plesk sử dụng (thống kê web hoặc xác thực chứng chỉ) nên không thể chuyển tiếp qua proxy.',
    'errorMaxApps' => 'Thuê bao này đã đạt số lượng ứng dụng được bật tối đa (%%max%%).',
    'errorFetchUrl' => 'Hãy nhập một URL https:// (tối đa 2048 ký tự, không có khoảng trắng).',
    'errorFetchHttps' => 'Chỉ có thể tải xuống từ URL https://.',
    'errorSampleNotEmpty' => 'Thư mục gốc ứng dụng không trống. Hãy xác nhận cho phép ứng dụng mẫu ghi đè tệp. %%details%%',
    'errorSampleUnix' => 'Máy chủ PHP mặc định (php -S) không thể lắng nghe trên socket Unix: hãy cài đặt bộ công cụ FrankenPHP hoặc chọn TCP.',
    'errorFetchSha256' => 'Tổng kiểm tra SHA-256 phải gồm 64 ký tự thập lục phân.',
    'errorFetchFilename' => 'Tên tệp chỉ được chứa chữ cái, chữ số và . _ + - (tối đa 128 ký tự).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Giới hạn bộ nhớ (MiB)',
    'fieldCpuPercent' => 'Giới hạn CPU (%)',
    'fieldTasks' => 'Giới hạn tiến trình / luồng',

    // Messages
    'messageSavedEnabled' => 'Đã lưu cài đặt và ứng dụng đang được khởi động (lại).',
    'messageSavedBuilding' => 'Đã lưu cài đặt. Ứng dụng đang được biên dịch và sẽ được khởi động (lại) khi biên dịch thành công; hãy theo dõi tiến độ trong nhật ký "Biên dịch & triển khai".',
    'messageSavedBuildNotStarted' => 'Đã lưu cài đặt nhưng không thể bắt đầu biên dịch: %%details%%',
    'messageSavedDisabled' => 'Đã lưu cài đặt. Ứng dụng đã bị tắt.',
    'messageAction_start' => 'Ứng dụng đang khởi động.',
    'messageAction_stop' => 'Ứng dụng đã dừng và sẽ giữ trạng thái dừng cho đến khi bạn khởi động lại.',
    'messageAction_restart' => 'Ứng dụng đang khởi động lại.',
    'messageDeployStarted' => 'Đã bắt đầu biên dịch. Hãy theo dõi tiến độ trong nhật ký "Biên dịch & triển khai".',
    'messageRemoved' => 'Đã gỡ bỏ ứng dụng.',
    'messageJobStarted' => 'Tác vụ đã bắt đầu. Tiến độ được hiển thị bên dưới.',
    'messageToolchainRemoved' => 'Đã gỡ bỏ %%version%%.',
    'messageSampleWritten' => 'Đã ghi ứng dụng mẫu (%%count%% tệp) và cập nhật cài đặt.',
    'messageSampleWrittenOne' => 'Đã ghi ứng dụng mẫu (một tệp) và cập nhật cài đặt.',
    'messageFetchStarted' => 'Đã bắt đầu tải xuống. Hãy theo dõi tiến độ trong nhật ký "Biên dịch & triển khai".',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Liệt kê các ứng dụng đã cấu hình và trạng thái của chúng.',
    'cli.commands.status' => 'Hiển thị trạng thái ứng dụng của một tên miền: --status <tên-miền>',
    'cli.commands.start' => 'Khởi động ứng dụng của một tên miền: --start <tên-miền>',
    'cli.commands.stop' => 'Dừng ứng dụng của một tên miền; ứng dụng giữ trạng thái dừng (kể cả sau khi khởi động lại máy chủ hoặc triển khai) cho đến khi dùng --start hoặc --restart: --stop <tên-miền>',
    'cli.commands.restart' => 'Khởi động lại ứng dụng của một tên miền: --restart <tên-miền>',
    'cli.commands.deploy' => 'Biên dịch và khởi động lại ứng dụng của một tên miền rồi chờ kết quả (ứng dụng đã dừng sẽ được biên dịch nhưng vẫn giữ trạng thái dừng): --deploy <tên-miền> [-no-wait]',
    'cli.commands.enable' => 'Bật ứng dụng đã cấu hình của một tên miền: --enable <tên-miền>',
    'cli.commands.disable' => 'Tắt ứng dụng của một tên miền: --disable <tên-miền>',
    'cli.commands.toolchains' => 'Liệt kê các bộ công cụ đã cài đặt và các tên miền đang dùng chúng.',
    'cli.commands.install-toolchain' => 'Cài đặt một bộ công cụ và chờ kết quả: --install-toolchain <môi-trường-chạy> <phiên-bản> [-no-wait]',
    'cli.commands.reconcile' => 'Đồng bộ các dịch vụ ứng dụng với Plesk (tên miền đã bị xóa, đổi tên hoặc tạm ngưng).',
];

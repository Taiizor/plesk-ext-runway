<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// French translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../fr-FR.php; the frontend strings live in ../app/fr-FR.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Installez des chaînes d\'outils et exécutez des applications en tant que services, sans Docker.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Compilez et exécutez sur ce domaine une application Go, Rust, Bun, Java, .NET, Python, Ruby, PHP ou précompilée.',
    'permissionName' => 'Gestion des applications Runway',
    'permissionDescription' => 'Permet au client de compiler et d\'exécuter des applications en tant que services d\'arrière-plan avec Runway.',

    // Errors
    'errorHelperFailed' => 'Le helper privilégié a échoué : %%details%%',
    'errorAccessDenied' => 'Accès refusé.',
    'errorNoDomain' => 'Le domaine est introuvable.',
    'errorNoHosting' => 'Ce domaine n\'a pas d\'hébergement Web.',
    'errorNotConfigured' => 'L\'application n\'est pas encore configurée. Enregistrez d\'abord les paramètres.',
    'errorInvalidOperation' => 'Opération non valide.',
    'errorInvalidValue' => 'Valeur non valide.',
    'errorPostRequired' => 'Cette action nécessite une requête POST.',
    'errorInternal' => 'Une erreur interne s\'est produite. Les détails se trouvent dans le journal du panneau Plesk.',
    'errorRuntime' => 'Choisissez un environnement d\'exécution valide.',
    'errorToolchain' => 'Choisissez une version de chaîne d\'outils valide.',
    'errorAppRoot' => 'La racine de l\'application doit être un chemin à l\'intérieur de l\'abonnement (lettres, chiffres et . _ - @ + /), sans segment "." ni "..".',
    'errorBuildCmd' => 'La commande de compilation est trop longue ou contient des caractères de contrôle.',
    'errorStartCmd' => 'La commande de démarrage doit tenir sur une seule ligne, sans caractères de contrôle (1000 caractères max.).',
    'errorStartCmdEmpty' => 'Une commande de démarrage est requise pour activer l\'application.',
    'errorLimit' => 'Le champ « %%name%% » doit contenir un nombre entier compris dans la plage autorisée.',
    'errorEnvLine' => 'Ligne %%line%% : utilisez le format CLÉ=valeur.',
    'errorEnvKey' => 'Ligne %%line%% : "%%key%%" n\'est pas un nom de variable valide.',
    'errorEnvReserved' => '%%key%% est géré par Runway et ne peut pas être défini.',
    'errorEnvLoader' => '%%key%% ne peut pas être défini ici ; placez-le dans la commande de démarrage (ex. %%key%%=... ./app).',
    'errorEnvValue' => 'La valeur de %%key%% ne doit pas contenir de sauts de ligne ni de caractères de contrôle.',
    'errorEnvTooMany' => 'Trop de variables d\'environnement (200 au maximum).',
    'errorListen' => 'Choisissez un mode d\'écoute valide.',
    'errorMode' => 'Choisissez un mode d\'application valide.',
    'errorMountPath' => 'Le chemin d\'URL doit être de la forme /api (lettres, chiffres et . _ ~ -).',
    'errorStaticPaths' => 'Les chemins statiques doivent être une liste de chemins d\'URL.',
    'errorStaticPath' => '"%%path%%" n\'est pas un chemin d\'URL valide (exemple : /assets).',
    'errorStaticPathsTooMany' => 'Le nombre de chemins statiques est limité à %%max%%.',
    'errorStaticPathsTooLong' => 'Les chemins statiques sont trop longs au total (%%max%% caractères au maximum).',
    'errorConfigTooLarge' => 'Les paramètres sont trop longs au total (%%length%% caractères, %%max%% au maximum) : raccourcissez les commandes ou les chemins.',
    'errorHealthPath' => 'Le chemin de vérification d\'état doit être un chemin d\'URL comme /healthz.',
    'errorPortRange' => 'Le premier port ne doit pas être supérieur au dernier port.',
    'errorSettingRange' => 'Saisissez un nombre entier compris entre %%min%% et %%max%%.',
    'errorListenMode' => 'Un worker d\'arrière-plan n\'a pas d\'écouteur : choisissez « Aucun » comme mode d\'écoute, ou un mode Web avec un port TCP ou un socket Unix.',
    'errorMountPathReserved' => '%%path%% est utilisé par Plesk (statistiques Web ou validation de certificat) et ne peut pas être relayé vers l\'application.',
    'errorMaxApps' => 'Cet abonnement a déjà atteint le nombre maximal d\'applications activées (%%max%%).',
    'errorFetchUrl' => 'Saisissez une URL https:// (2048 caractères max., sans espaces).',
    'errorFetchHttps' => 'Seules les URL https:// peuvent être téléchargées.',
    'errorSampleNotEmpty' => 'La racine de l\'application n\'est pas vide. Confirmez que l\'exemple peut écraser des fichiers. %%details%%',
    'errorSampleUnix' => 'Le serveur PHP par défaut (php -S) ne peut pas écouter sur un socket Unix : installez une chaîne d\'outils FrankenPHP ou choisissez TCP.',
    'errorFetchSha256' => 'La somme de contrôle SHA-256 doit comporter 64 caractères hexadécimaux.',
    'errorFetchFilename' => 'Le nom de fichier ne peut contenir que des lettres, des chiffres et . _ + - (128 caractères max.).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Limite de mémoire (Mio)',
    'fieldCpuPercent' => 'Limite de CPU (%)',
    'fieldTasks' => 'Limite de processus / threads',

    // Messages
    'messageSavedEnabled' => 'Les paramètres ont été enregistrés et l\'application est en cours de (re)démarrage.',
    'messageSavedBuilding' => 'Les paramètres ont été enregistrés. L\'application est en cours de compilation et sera (re)démarrée si la compilation réussit ; suivez-la dans le journal « Compilation et déploiement ».',
    'messageSavedBuildNotStarted' => 'Les paramètres ont été enregistrés, mais la compilation n\'a pas pu être lancée : %%details%%',
    'messageSavedDisabled' => 'Les paramètres ont été enregistrés. L\'application est désactivée.',
    'messageAction_start' => 'L\'application démarre.',
    'messageAction_stop' => 'L\'application a été arrêtée. Elle reste arrêtée jusqu\'à ce que vous la redémarriez.',
    'messageAction_restart' => 'L\'application redémarre.',
    'messageDeployStarted' => 'La compilation a démarré. Suivez-la dans le journal « Compilation et déploiement ».',
    'messageRemoved' => 'L\'application a été supprimée.',
    'messageJobStarted' => 'La tâche a démarré. Sa progression est affichée ci-dessous.',
    'messageToolchainRemoved' => 'La version %%version%% a été supprimée.',
    'messageSampleWritten' => 'L\'exemple d\'application a été écrit (%%count%% fichiers) et les paramètres ont été mis à jour.',
    'messageSampleWrittenOne' => 'L\'exemple d\'application a été écrit (un fichier) et les paramètres ont été mis à jour.',
    'messageFetchStarted' => 'Le téléchargement a démarré. Suivez-le dans le journal « Compilation et déploiement ».',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Liste les applications configurées et leur état.',
    'cli.commands.status' => 'Affiche l\'état de l\'application d\'un domaine : --status <domaine>',
    'cli.commands.start' => 'Démarre l\'application d\'un domaine : --start <domaine>',
    'cli.commands.stop' => 'Arrête l\'application d\'un domaine ; elle reste arrêtée (même après un redémarrage du serveur ou un déploiement) jusqu\'à --start ou --restart : --stop <domaine>',
    'cli.commands.restart' => 'Redémarre l\'application d\'un domaine : --restart <domaine>',
    'cli.commands.deploy' => 'Compile et redémarre l\'application d\'un domaine et attend le résultat (une application arrêtée est compilée mais reste arrêtée) : --deploy <domaine> [-no-wait]',
    'cli.commands.enable' => 'Active l\'application configurée d\'un domaine : --enable <domaine>',
    'cli.commands.disable' => 'Désactive l\'application d\'un domaine : --disable <domaine>',
    'cli.commands.toolchains' => 'Liste les chaînes d\'outils installées et les domaines qui les utilisent.',
    'cli.commands.install-toolchain' => 'Installe une chaîne d\'outils et attend le résultat : --install-toolchain <environnement> <version> [-no-wait]',
    'cli.commands.reconcile' => 'Aligne les services des applications sur Plesk (domaines supprimés, renommés ou suspendus).',
];

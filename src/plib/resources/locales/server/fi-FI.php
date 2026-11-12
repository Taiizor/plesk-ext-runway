<?php
// Copyright 2026 Taiizor. Licensed under the MIT License.
// Finnish translation
//
// Server strings, used by PHP through pm_Locale::lmsg() (API messages, validation errors,
// buttons, permission, "plesk ext runway --help" descriptions: keys "cli.commands.<command>").
// Loaded by ../fi-FI.php; the frontend strings live in ../app/fi-FI.php.
// Placeholders use %%name%%. One entry per line (tests/check_locales.py parses this file).

return [
    // Navigation and permission
    'buttonAdminTitle' => 'Runway',
    'buttonAdminDescription' => 'Asenna työkaluketjuja ja suorita sovelluksia palveluina ilman Dockeria.',
    'buttonDomainTitle' => 'Runway',
    'buttonDomainDescription' => 'Koosta ja suorita Go-, Rust-, Bun-, Java-, .NET-, Python-, Ruby-, PHP- tai valmiiksi käännetty sovellus tällä toimialueella.',
    'permissionName' => 'Runway-sovellusten hallinta',
    'permissionDescription' => 'Sallii asiakkaan koostaa ja suorittaa sovelluksia taustapalveluina Runwayn avulla.',

    // Errors
    'errorHelperFailed' => 'Etuoikeutettu apuohjelma epäonnistui: %%details%%',
    'errorAccessDenied' => 'Käyttö estetty.',
    'errorNoDomain' => 'Toimialuetta ei löytynyt.',
    'errorNoHosting' => 'Toimialueella ei ole web-isännöintiä.',
    'errorNotConfigured' => 'Sovellusta ei ole vielä määritetty. Tallenna asetukset ensin.',
    'errorInvalidOperation' => 'Virheellinen toiminto.',
    'errorInvalidValue' => 'Virheellinen arvo.',
    'errorPostRequired' => 'Tämä toiminto edellyttää POST-pyyntöä.',
    'errorInternal' => 'Tapahtui sisäinen virhe. Lisätiedot löytyvät Plesk-paneelin lokista.',
    'errorRuntime' => 'Valitse kelvollinen ajoympäristö.',
    'errorToolchain' => 'Valitse kelvollinen työkaluketjun versio.',
    'errorAppRoot' => 'Sovelluksen juurihakemiston on oltava tilauksen sisällä oleva polku (kirjaimia, numeroita sekä . _ - @ + /) ilman "."- tai ".."-osia.',
    'errorBuildCmd' => 'Koontikomento on liian pitkä tai sisältää ohjausmerkkejä.',
    'errorStartCmd' => 'Käynnistyskomennon on oltava yksi rivi ilman ohjausmerkkejä (enintään 1000 merkkiä).',
    'errorStartCmdEmpty' => 'Käynnistyskomento tarvitaan, jotta sovelluksen voi ottaa käyttöön.',
    'errorLimit' => 'Kentän %%name%% on oltava sallitulla alueella oleva kokonaisluku.',
    'errorEnvLine' => 'Rivi %%line%%: käytä muotoa AVAIN=arvo.',
    'errorEnvKey' => 'Rivi %%line%%: "%%key%%" ei ole kelvollinen muuttujan nimi.',
    'errorEnvReserved' => 'Runway hallitsee muuttujaa %%key%%, eikä sitä voi asettaa.',
    'errorEnvLoader' => 'Muuttujaa %%key%% ei voi asettaa tässä; lisää se käynnistyskomentoon (esim. %%key%%=... ./app).',
    'errorEnvValue' => 'Muuttujan %%key%% arvo ei saa sisältää rivinvaihtoja tai ohjausmerkkejä.',
    'errorEnvTooMany' => 'Liian monta ympäristömuuttujaa (enintään 200).',
    'errorListen' => 'Valitse kelvollinen kuuntelutapa.',
    'errorMode' => 'Valitse kelvollinen sovellustila.',
    'errorMountPath' => 'Anna URL-polku, kuten /api (kirjaimia, numeroita sekä . _ ~ -).',
    'errorStaticPaths' => 'Staattisten polkujen on oltava luettelo URL-polkuja.',
    'errorStaticPath' => '"%%path%%" ei ole kelvollinen URL-polku (esimerkki: /assets).',
    'errorStaticPathsTooMany' => 'Staattisia polkuja voi olla enintään %%max%%.',
    'errorStaticPathsTooLong' => 'Staattiset polut ovat yhteensä liian pitkiä (enintään %%max%% merkkiä).',
    'errorConfigTooLarge' => 'Asetukset ovat yhteensä liian pitkiä (%%length%% merkkiä, enintään %%max%%): lyhennä komentoja tai polkuja.',
    'errorHealthPath' => 'Kuntotarkistuksen polun on oltava URL-polku, kuten /healthz.',
    'errorPortRange' => 'Ensimmäinen portti ei saa olla suurempi kuin viimeinen portti.',
    'errorSettingRange' => 'Anna kokonaisluku väliltä %%min%%–%%max%%.',
    'errorListenMode' => 'Taustaprosessilla ei ole kuuntelijaa: valitse kuuntelutavaksi "Ei mitään" tai web-tila, jossa on TCP-portti tai Unix-soketti.',
    'errorMountPathReserved' => 'Plesk käyttää polkua %%path%% (web-tilastot tai varmenteen vahvistus), eikä sitä voi välittää sovellukselle.',
    'errorMaxApps' => 'Tällä tilauksella on jo enimmäismäärä käytössä olevia sovelluksia (%%max%%).',
    'errorFetchUrl' => 'Anna https://-osoite (enintään 2048 merkkiä, ilman välilyöntejä).',
    'errorFetchHttps' => 'Vain https://-osoitteita voi ladata.',
    'errorSampleNotEmpty' => 'Sovelluksen juurihakemisto ei ole tyhjä. Vahvista, että esimerkkisovellus saa korvata tiedostoja. %%details%%',
    'errorSampleUnix' => 'PHP:n oletuspalvelin (php -S) ei voi kuunnella Unix-sokettia: asenna FrankenPHP-työkaluketju tai valitse TCP.',
    'errorFetchSha256' => 'SHA-256-tarkistussumman on oltava 64 heksadesimaalimerkkiä.',
    'errorFetchFilename' => 'Tiedostonimi saa sisältää vain kirjaimia, numeroita sekä . _ + - (enintään 128 merkkiä).',

    // Field names used in error messages
    'fieldMemoryMb' => 'Muistiraja (MiB)',
    'fieldCpuPercent' => 'Suoritinraja (%)',
    'fieldTasks' => 'Prosessi-/säieraja',

    // Messages
    'messageSavedEnabled' => 'Asetukset tallennettiin, ja sovellusta käynnistetään (uudelleen).',
    'messageSavedBuilding' => 'Asetukset tallennettiin. Sovellusta koostetaan, ja se käynnistetään (uudelleen), kun koonti onnistuu; seuraa sitä "Koonti ja käyttöönotto" -lokista.',
    'messageSavedBuildNotStarted' => 'Asetukset tallennettiin, mutta koontia ei voitu käynnistää: %%details%%',
    'messageSavedDisabled' => 'Asetukset tallennettiin. Sovellus on pois käytöstä.',
    'messageAction_start' => 'Sovellus käynnistyy.',
    'messageAction_stop' => 'Sovellus pysäytettiin. Se pysyy pysäytettynä, kunnes käynnistät sen uudelleen.',
    'messageAction_restart' => 'Sovellus käynnistyy uudelleen.',
    'messageDeployStarted' => 'Koonti on alkanut. Seuraa sitä "Koonti ja käyttöönotto" -lokista.',
    'messageRemoved' => 'Sovellus poistettiin.',
    'messageJobStarted' => 'Työ on alkanut. Sen edistyminen näkyy alla.',
    'messageToolchainRemoved' => '%%version%% poistettiin.',
    'messageSampleWritten' => 'Esimerkkisovellus kirjoitettiin (%%count%% tiedostoa) ja asetukset päivitettiin.',
    'messageSampleWrittenOne' => 'Esimerkkisovellus kirjoitettiin (yksi tiedosto) ja asetukset päivitettiin.',
    'messageFetchStarted' => 'Lataus on alkanut. Seuraa sitä "Koonti ja käyttöönotto" -lokista.',

    // Command line: descriptions shown by "plesk ext runway --help"
    'cli.commands.list' => 'Luettelee määritetyt sovellukset ja niiden tilan.',
    'cli.commands.status' => 'Näyttää toimialueen sovelluksen tilan: --status <toimialue>',
    'cli.commands.start' => 'Käynnistää toimialueen sovelluksen: --start <toimialue>',
    'cli.commands.stop' => 'Pysäyttää toimialueen sovelluksen; se pysyy pysäytettynä (myös palvelimen uudelleenkäynnistyksen tai käyttöönoton jälkeen), kunnes annetaan --start tai --restart: --stop <toimialue>',
    'cli.commands.restart' => 'Käynnistää toimialueen sovelluksen uudelleen: --restart <toimialue>',
    'cli.commands.deploy' => 'Koostaa ja käynnistää toimialueen sovelluksen uudelleen ja odottaa tulosta (pysäytetty sovellus koostetaan, mutta se pysyy pysäytettynä): --deploy <toimialue> [-no-wait]',
    'cli.commands.enable' => 'Ottaa toimialueen määritetyn sovelluksen käyttöön: --enable <toimialue>',
    'cli.commands.disable' => 'Poistaa toimialueen sovelluksen käytöstä: --disable <toimialue>',
    'cli.commands.toolchains' => 'Luettelee asennetut työkaluketjut ja niitä käyttävät toimialueet.',
    'cli.commands.install-toolchain' => 'Asentaa työkaluketjun ja odottaa tulosta: --install-toolchain <ajoympäristö> <versio> [-no-wait]',
    'cli.commands.reconcile' => 'Saattaa sovelluspalvelut Pleskin mukaisiksi (poistetut, uudelleennimetyt tai keskeytetyt toimialueet).',
];

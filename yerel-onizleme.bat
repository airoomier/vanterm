@echo off
chcp 65001 >nul
title Vanterm yerel onizleme
cd /d "%~dp0site"
echo Vanterm sitesi http://localhost:8080/ adresinde aciliyor...
echo Kapatmak icin bu pencereyi kapatin.
echo.
where php >nul 2>nul && (start "" http://localhost:8080/ & php -S localhost:8080 & goto :eof)
where node >nul 2>nul && (start "" http://localhost:8080/ & npx --yes http-server -p 8080 -c-1 & goto :eof)
where python >nul 2>nul && (start "" http://localhost:8080/ & python -m http.server 8080 & goto :eof)
where py >nul 2>nul && (start "" http://localhost:8080/ & py -m http.server 8080 & goto :eof)
echo PHP, Node.js veya Python bulunamadi. Birini kurup tekrar deneyin.
pause

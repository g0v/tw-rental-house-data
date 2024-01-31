#!/bin/bash

# file path that contains target raw zip files, say, datas/q1/[202501][CSV][Raw] TW-Rental-Data.zip
rawFilePath=$1

unzip "$rawFilePath"
echo === RAW CSV ===
wc -l tw-rental-data/*.csv
cat tw-rental-data/*.json
echo 
du -b tw-rental-data/*.csv
rm -rf tw-rental-data
echo
mkdir tw-rental-data
cp -R 編碼表 tw-rental-data
zip "$rawFilePath" tw-rental-data/編碼表/*
rm -rf tw-rental-data

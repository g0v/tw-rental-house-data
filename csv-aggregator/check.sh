#!/bin/bash

month=$1

csvFile=\[$month\]\[CSV\]
jsonFile=\[$month\]\[JSON\]

rawCsvFile="$csvFile"\[Raw\]
dedupCsvFile="$csvFile"\[Deduplicated\]

rawJsonFile="$jsonFile"\[Raw\]
dedupJsonFile="$jsonFile"\[Deduplicated\]

fileTail=" TW-Rental-Data.zip"

unzip "$rawCsvFile"*
echo === RAW CSV ===
wc -l tw-rental-data/*.csv
cat tw-rental-data/*.json
echo 
du -b tw-rental-data/*.csv
rm -rf tw-rental-data
echo
mkdir tw-rental-data
cp -R 編碼表 tw-rental-data
zip "$rawCsvFile$fileTail" tw-rental-data/編碼表/*
rm -rf tw-rental-data

if [ -f "$rawJsonFile$fileTail" ]; then
  unzip "$rawJsonFile"*
  echo === RAW JSON ===
  wc -l tw-rental-data/*
  wc -l tw-rental-data/* | wc -l
  du -b tw-rental-data
  rm -rf tw-rental-data
  echo
  mkdir tw-rental-data
  cp -R 編碼表 tw-rental-data
  zip "$rawJsonFile$fileTail" tw-rental-data/編碼表/*
  rm -rf tw-rental-data
fi

unzip "$dedupCsvFile"*
echo === Dedup CSV ===
wc -l tw-rental-data/*.csv
cat tw-rental-data/*.json
echo 
du -b tw-rental-data/*.csv
rm -rf tw-rental-data
echo
mkdir tw-rental-data
cp -R 編碼表 tw-rental-data
zip "$dedupCsvFile$fileTail" tw-rental-data/編碼表/*
rm -rf tw-rental-data

if [ -f "$dedupJsonFile$fileTail"]; then
  unzip "$dedupJsonFile"*
  echo === Dedup JSON ===
  wc -l tw-rental-data/*
  wc -l tw-rental-data/* | wc -l
  du -b tw-rental-data
  rm -rf tw-rental-data
  echo
  mkdir tw-rental-data
  cp -R 編碼表 tw-rental-data
  zip "$dedupJsonFile$fileTail" tw-rental-data/編碼表/*
  rm -rf tw-rental-data
fi

# unzip "$dedupCsvFile"*


## csv

## json
#wc -l tw-rental-data/* && wc -l tw-rental-data/* | wc -l && du -b tw-rental-data

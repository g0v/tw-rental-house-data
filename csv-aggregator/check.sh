#!/bin/bash

# Accept either:
#   1. A raw zip file, e.g. datas/q1/[202501][CSV][Raw] TW-Rental-Data.zip
#   2. A plain CSV file, e.g. 202604-raw.csv (will be packed into zip first)
input=$1

if [[ "$input" == *.csv ]]; then
  # Extract YYYYMM from filename like 202604-raw.csv
  basename=$(basename "$input")
  yearmonth="${basename%%-*}"
  rawFilePath="[${yearmonth}][CSV][Raw] TW-Rental-Data.zip"

  # Count lines (subtract header) for json metadata
  total=$(( $(wc -l < "$input") - 1 ))

  # Pack into zip structure
  rm -rf tw-rental-data
  mkdir -p tw-rental-data
  cp "$input" "tw-rental-data/${yearmonth}-raw.csv"
  echo "{\"_total\": ${total}, \"591 租屋網\": ${total}}" > "tw-rental-data/${yearmonth}-raw.json"
  cp -R 編碼表 tw-rental-data/
  zip -r "$rawFilePath" tw-rental-data/
  rm -rf tw-rental-data
  echo "Packed $input -> $rawFilePath"
  echo
fi

rawFilePath="${rawFilePath:-$input}"

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

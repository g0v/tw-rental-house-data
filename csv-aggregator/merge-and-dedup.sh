#!/bin/bash

set -e

# change to the directory that contains this script
cd "$(dirname "$0")"

# directory that contains all raw zip files, say, [202501][CSV][Raw] TW-Rental-Data.zip
sourceDir=$1

# result name, say, 2025Q1, the result will be
# 1. [2025Q1][CSV][Raw] TW-Rental-Data.zip
# 2. [2025Q1][CSV][[Deduplicated] TW-Rental-Data.zip
targetName=$2

# exit if sourceDir or targetName is not specified
if [ -z "$sourceDir" ] || [ -z "$targetName" ]; then
  echo "Usage: $0 <sourceDir> <targetName>"
  exit 1
fi

# unzip files to a temp directory
tempDir=`mktemp -d`

# remove tempDir at the end
trap "rm -rf $tempDir" EXIT

# file in zip may contain space
mkdir $tempDir/raw $tempDir/result $tempDir/tw-rental-data
IFS=$'\n'
for file in `ls $sourceDir/*.zip`; do
  unzip "$file" -d $tempDir/raw
  # move aaa dir to $tempDir/raw if not existed
  if [ ! -d "$tempDir/tw-rental-data/編碼表" ]; then
    mv $tempDir/raw/tw-rental-data/編碼表 $tempDir/tw-rental-data
  else
    rm -rf $tempDir/raw/tw-rental-data/編碼表
  fi
done

mv $tempDir/raw/tw-rental-data/*-raw.csv $tempDir/raw

cp merge-multiple.sql $tempDir

echo "Merge files..."
(cd $tempDir; clickhouse local --queries-file merge-multiple.sql)

ls -l $tempDir/result/raw.csv
ls -l $tempDir/result/deduplicated.csv

mv $tempDir/result/raw.csv "$tempDir/tw-rental-data/${targetName}-raw.csv"
(cd $tempDir; zip -r "[$targetName][CSV][Raw] TW-Rental-Data.zip" tw-rental-data; mv tw-rental-data/*.csv ./result)

mv $tempDir/result/deduplicated.csv "$tempDir/tw-rental-data/$targetName-deduplicated.csv"
(cd $tempDir; zip -r "[$targetName][CSV][Deduplicated] TW-Rental-Data.zip" tw-rental-data/)

echo "Result:"
(cd $tempDir; ls -lh *.zip)

mv $tempDir/*.zip .



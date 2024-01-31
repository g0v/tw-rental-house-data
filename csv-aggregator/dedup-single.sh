#!/bin/bash -e

# change to the directory that contains this script
cd "$(dirname "$0")"

# file path that contains target raw zip files, say, datas/q1/[202501][CSV][Raw] TW-Rental-Data.zip
# the result dedup file will become datas/q1/[202501][CSV][Deduplicated] TW-Rental-Data.zip
rawPath=$1

# exit if rawPath or targetName is not specified
if [ -z "$rawPath" ]; then
  echo "Usage: $0 <sourcePath>"
  exit 1
fi

# convert datas/q1/[202501][CSV][Raw] TW-Rental-Data.zip to 202501
targetName=`basename "$rawPath" | cut -c 2-7`

# unzip files to a temp directory
tempDir=`mktemp -d`

# remove tempDir at the end
trap "rm -rf $tempDir" EXIT

# file in zip may contain space
mkdir $tempDir/raw $tempDir/result $tempDir/tw-rental-data

unzip "$rawPath" -d $tempDir/raw
# move a dir to $tempDir/raw if not existed
if [ ! -d "$tempDir/tw-rental-data/編碼表" ]; then
  mv $tempDir/raw/tw-rental-data/編碼表 $tempDir/tw-rental-data
else
  rm -rf $tempDir/raw/tw-rental-data/編碼表
fi

mv $tempDir/raw/tw-rental-data/*-raw.csv $tempDir/raw

cp dedup-single.sql $tempDir

echo "Merge files..."
(cd $tempDir; clickhouse local --queries-file dedup-single.sql)

ls -l $tempDir/result/deduplicated.csv

mv $tempDir/result/deduplicated.csv "$tempDir/tw-rental-data/$targetName-deduplicated.csv"
(cd $tempDir; zip -r "[$targetName][CSV][Deduplicated] TW-Rental-Data.zip" tw-rental-data/)

echo "Result:"
(cd $tempDir; ls -lh *.zip)

mv $tempDir/*.zip .



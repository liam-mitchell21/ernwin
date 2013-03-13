#!/bin/bash

#set -x

rm -rf best; rm -rf cluster_error; rm -rf cluster_output; mkdir cluster_output; mkdir cluster_error; { for name in $(cat sorted_test_file_list.txt); do for i in $(seq 1); do echo $name $i; mkdir -p best/${name}/${i}; done; done; } | \
    shuf | \
    parallel --eta --colsep ' '  \
    'qsub -cwd -V -l h="!qc05" -o cluster_output -e cluster_error -b y ./bobbins/scripts/gibbs.py -my -i 4000 --output-file best/{1}/{2}/out.txt --output-dir best/{1}/{2}/ ~/data/ernwin/processed/{1}/graph/temp.comp'


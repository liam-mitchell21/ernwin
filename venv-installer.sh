#!/bin/bash

### TODO: variableize paths

echo "This should do a fresh install to produce a workable ernwin within a conda venv"

sleep 2

####### download miniconda if it doesnt exist yet ###################
if [ ! -d ~/miniconda2 ]; then
    wget -P ~ https://repo.anaconda.com/miniconda/Miniconda2-latest-Linux-x86_64.sh
fi


###### install miniconda, please use defaults #################
bash ~/Miniconda2*.sh

rm ~/Miniconda2*.sh

######### make new venv #####################

~/miniconda2/bin/conda create -n ernwinenv python=2.7 -y

########### install pip #################

~/miniconda2/bin/conda install -n ernwinenv pip -y

########### activate env ####################

source ~/miniconda2/etc/profile.d/conda.sh

conda activate ernwinenv

########## dependencies ###################

conda install freetype -y #prereq for matplotlib, fails on pip for some reason

############# forgi ####################

cd ..
git clone https://github.com/ViennaRNA/forgi.git
# af37f45caba6bb944be0c4a39c88f63723f6cc82
cd forgi
pip install -r requirements.txt
python setup.py build
python setup.py install
cd ../ernwin

############### rest of them ##########

pip install -r requirements.txt

python setup.py build
python setup.py install

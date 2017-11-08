#!python
from __future__ import absolute_import, division, print_function, unicode_literals
from builtins import (ascii, bytes, chr, dict, filter, hex, input, #pip install future
                      int, map, next, oct, open, pow, range, round,
                      str, super, zip) #future package
from future.builtins.disabled import (apply, cmp, coerce, execfile,
                             file, long, raw_input, reduce, reload,
                             unicode, xrange, StandardError)

import argparse
import sys
import warnings
import copy
import os
import random
import math
import re
import os.path as op
import contextlib
import itertools as it
import subprocess
import operator
import logging

import scipy.ndimage
import numpy as np


import forgi.threedee.model.coarse_grain as ftmc
import forgi.threedee.model.stats as ftms
import forgi.threedee.utilities.graph_pdb as ftug
import forgi.graph.bulge_graph as fgb
import forgi.utilities.debug as fud
import forgi.utilities.commandline_utils as fuc
from fess.builder import energy as fbe
from fess.builder import models as fbm
from fess.builder import sampling as fbs
from fess.builder import builder as fbb
from fess.builder import replicaExchange as fbr
from fess.builder import config
from fess.builder import monitor as sstats
from fess.builder import stat_container
from fess.builder import move as fbmov
from fess import data_file, __version__
import fess
import forgi
from fess.motif import annotate as fma
from fess.aux.utils import get_version_string

log = logging.getLogger(__name__)

#Magic numbers
DEFAULT_ENERGY_PREFACTOR=30



def get_parser():
    """
    Here all commandline & help-messages arguments are defined.

    :returns: an instance of argparse.ArgumentParser
    """
    parser = fuc.get_rna_input_parser("ERNWIN: Coarse-grained sampling of RNA 3D structures.", nargs=1, parser_kwargs={"formatter_class":argparse.RawTextHelpFormatter})

    general_behavior = parser.add_argument_group("General behaviour",
                                    description="These options modify the general bahaviour of ERNWIN")
    general_behavior.add_argument('--new-sampling', action="store_true",
                                  help="Use the new sampling procedure.")
    general_behavior.add_argument('--new-sampling-r-cutoff', type=int, default=8,
                                  help="Cutoff in angstrom for new sampling procedure.")
    general_behavior.add_argument('--new-sampling-a-weight', type=int, default=3,
                                  help="Cutoff in degrees for new sampling procedure.")
    general_behavior.add_argument('--new-sampling-t-weight', type=int, default=4,
                                  help="Cutoff in degrees for new sampling procedure.")


    general_behavior.add_argument('-i', '--iterations', action='store', default=10000, help='Number of structures to generate', type=int)
    general_behavior.add_argument('--start-from-scratch', default=False, action='store_true',
                        help="Do not attempt to start at the input conformation.\n"
                             "(Automatically True for fasta files.)")
    general_behavior.add_argument('-f', '--fair-building', action="store_true",
                        help = "Try to build the structure using a fair \n"
                               "but slow algorithm.\n "
                               "This flag implies --start-from-scratch")
    general_behavior.add_argument('--fair-building-mst', action="store_true",
                        help = "Try to build the structure using a fair \n"
                               "but slow algorithm for multiple MSTs.\n "
                               "This flag implies --start-from-scratch")
    general_behavior.add_argument('--fair-building-d', action="store_true",
                        help = "EXPERIMENTAL! Like --fair-building, but use a \n"
                               "potentially faster and experimental algorithm \n"
                               "that is inspired by dimerization method for SAWs.\n "
                               "This flag implies --start-from-scratch")
    general_behavior.add_argument('--eval-energy', default=False, action='store_true',
                        help='Evaluate the energy of the input structure and\n'
                             'exit without sampling.')
    general_behavior.add_argument('--seed', action='store', help="Seed for the random number generator.",
                        type=int)
    general_behavior.add_argument('--move-set', default="Mover", help = fbmov.get_argparse_help())
    general_behavior.add_argument('--mst-breakpoints', type=str, help="During initial MST creation, prefer to \n"
                                                            "break the multiloops at the indicated nodes.\n"
                                                            "A comma-seperated list. E.g. 'm0,m10,m12'")
    general_behavior.add_argument('--replica-exchange', type=int, help="Experimental")
    general_behavior.add_argument('--parallel', action="store_true", help="Only useful for replica exchange. Spawn parallel processes.")

    output_options = parser.add_argument_group("Controlling output",
                                    description="These options control the output or ERNWIN")

    output_options.add_argument('--save-n-best', default=3,
                        help='Save the best (lowest energy) n structures.', type=int)
    output_options.add_argument('--save-min-rmsd', default=3,
                        help='Save the best (lowest rmsd) n structures.', type=int)
    output_options.add_argument('--step-save', default=0, help="Save the structure at every n'th step.",
                         type=int)
    output_options.add_argument('--dump-energies', default=False, action='store_true',
                        help='Dump the measures used for energy calculation to file') #UNUSED OPTION. REMOVE
    output_options.add_argument('--no-rmsd', default=False,
                        help='Refrain from trying to calculate the rmsd.', action='store_true')
    output_options.add_argument('--rmsd-to', action='store', type=str,
                        help="A *.cg/ *.coord or *.pdb file.\n"
                             "Calculate the RMSD and MCC relative to the structure\n"
                             "in this file, not to the structure used as starting\n"
                             "point for sampling.")
    output_options.add_argument('--dist', type=str,
                        help="One or more pairs of nucleotide positions.\n"
                             "The distance between these nucleotifdes will be \n"
                             "calculated.\n"
                             "Example: '1,15:3,20..' will print the distance between\n"
                             "          nucleoitide 1 and 15 and the distance \n"
                             "          between nucleotide 3 and 20.")
    #Controll output files
    output_options.add_argument('--output-file', action='store', type=str, default="out.log",
                        help="Filename for output (log). \n"
                             "This file will be created inside the --output-base-dir.\n"
                             "Default: out.log")
    output_options.add_argument('--output-base-dir', action='store', type=str, default="",
                        help="Base dir for the output. \n"
                              "In this directory, a subfolder with the name\n"
                              "from the fasta-file will be generated")
    output_options.add_argument('-o', '--output-dir-suffix', action='store', type=str,
                        default="", help="Suffix attached to the name from the fasta-file, \n"
                                         "used as name for the subfolder with all structures.")

    stat_options = parser.add_argument_group("Choosing stats",
                                    description="These options control what stats ERNWIN uses for sampling")
    stat_options.add_argument('--freeze', type=str, default="",
                            help= "A comma-seperated list of cg-element names.\n"
                                  "These elements will not be changed during samplig.")
    stat_options.add_argument('--stats-file', type=str, default=data_file("stats/all_nr2.110.stats"),
                        help= "A filename.\n"
                              "A file containing all the stats to sample from\n"
                              " for all coarse grained elements")
    stat_options.add_argument('--fallback-stats-files', nargs = '+', type=str,
                        help= "A list of fallback stats file that can be uses if insufficient stats "
                              "are found in the normal stats file for a coarse-grained element.\n"
                              "If more than one file is given, the files are used in the order specified.\n")
    stat_options.add_argument('--sequence-based', action="store_true",
                        help= "Take the sequence into account when choosing stats.")

    stat_options.add_argument('--clustered-angle-stats', type=str, action="store",
                        help= "A filename.\n"
                              "If given, use this instead of --stats-file for the\n"
                              " angle stats (interior and multi loops).\n"
                              "A clustered stats file can be created with\n"
                              "scrips/cluster_stats.py\n"
                              "This is used to sample equally from all CLUSTERS of\n"
                              "angle stats and is used to compensate for unequally\n"
                              "populated clusters.")
    stat_options.add_argument('--jar3d', action="store_true", help="Use JAR3D to restrict the stats \n"
                                                   "for interior loops to matching motifs.\n"
                                                   "Requires the correct paths to jar3d to be set in\n "
                                                   "fess.builder.config.py"   )
    #Controlling the energy
    energy_options = parser.add_argument_group("Energy",
                                        description="Choose the energy and constraint energy")

    energy_options.add_argument('--constraint-energy', default="D", action='store', type=str,
                                    help="The type of constraint energy to use. \n"
                                         "D=Default    clash- and junction closure energy\n"
                                         "B=Both       same as 'D'\n"
                                         "J=junction   only junction closure energy\n"
                                         "C=clash      only stem clash energy\n"
                                         "N=None       no constraint energy")
    energy_options.add_argument('-e', '--energy', default="D", action='store', type=str,
                    help= "The type of non-constraint energy to use. D=Default, N=None.\n"+
                          fbe.get_argparse_help()+
                          "\nExample: ROG,SLD,AME")
    energy_options.add_argument('--track-energies', action='store', type=str, default="",
                        help= "A ':' seperated list of combined energies.\n"
                              "Each energy is given in the format specified\n"
                              "for the --energy option.\n"
                              "These energies are not used for sampling, \n"
                              "but only calculated after each step.")
    energy_options.add_argument('--projected-dist', action='store', type=str, default="",
                        help= "A ':' seperated list of tripels: \n"
                              "cgelement, cgelement, dist\n"
                              "Where dist is the projected distance in the image \n"
                              "in Angstrom.\n"
                              "Example: 's1,h3,10:s2,h3,12'")
    energy_options.add_argument('--fpp-landmarks', action='store', type=str, default="",
                        help= "A ':' seperated list of tripels: \n"
                              "nucleotide-pos, x, y\n"
                              "Where 0,0 is the upperleft corner of the image\n"
                              "And the coordinates are in pixels\n"
                              "Example: '123,3,5'")
    energy_options.add_argument('--ref-img', action='store', type=str, default="",
                        help= "A black and white square image (e.g. in png format)\n"
                              "as a reference projection for the Hausdorff Energy.\n"
                              "White is the RNA, black is the background.\n"
                              "Requires the Python Imaging Library (PIL) or Pillow.")
    energy_options.add_argument('--scale', action='store', type=int,
                        help= "Used for the Hausdorff Energy.\n"
                              "The length (in Angstrom) of each side \n"
                              "of the image is")
    energy_options.add_argument('--clamp', action='store', type=str,
                        help= "Used for the CLA energy.\n"
                              "A list `p1,p2:p3,p4:...` where p1 and p2 are clamped\n"
                              "together and p3+p4 are clamped together. \n"
                              "The pi are either emelents ('s1','i1',...) or\n"
                              " integers (positions in the sequence).\n")
    return parser


def getHDEenergy(hde_image, scale, pre):
    img=scipy.ndimage.imread(hde_image)
    return fbe.HausdorffEnergy(img, scale, pre)

def getFPPArgs(cg, args):
    print ("GET FPP ENERGY")
    if not (args.ref_img and args.scale and args.fpp_landmarks):
        import Tkinter as tk
        from tkFileDialog import askopenfilename
        import tkMessageBox
        def on_closing():
            if tkMessageBox.askokcancel("Quit", "This will exit the complete ernwin script. Proceed?"):
                root.destroy()
                sys.exit(2)
        root = tk.Tk()
        root.protocol("WM_DELETE_WINDOW", on_closing)
    if args.ref_img:
        ref_image=args.ref_img
    else:
        # We open a file dialogue
        ref_image = askopenfilename(parent=root, title='Please choose the reference projection'
                                                       ' image for the FPP energy.',
                                    filetypes = [("Image Files", ("*.jpg", "*.png", "*.bmp")),
                                                 ("All", "*")])
    if not ref_image:
        print("No reference image selected. Aborting", file=sys.stderr)
        sys.exit(2)
    if args.scale:
        scale = args.scale
    else:
        lab = tk.Label(root, text="How many Angstrom is the width of the image?:")
        lab.pack()
        ent = tk.Entry(root)
        ent.pack()
        ent.focus_set()
        n={} #A workaround for the missing nonlocal statement in python 2
        def submit():
            s=ent.get()
            try:
              s=int(s)
            except:
              lab2 = tk.Label(root, text="Please use an integer value!")
              lab2.pack()
              ent.focus_set()
            else:
              n["scale"]=s
              root.destroy()
        b = tk.Button(root, text="OK", command=submit)
        b.pack()
        root.mainloop()

        scale = n["scale"]
    if args.fpp_landmarks:
        landmarks=args.fpp_landmarks.split(":")
        landmarks=[tuple(map(int, x.split(","))) for x in landmarks]
    else:
        from PIL import Image, ImageTk
        root.destroy() #In case the --scale was given.
        root = tk.Tk()
        root.title("Please select 3 landmarks")
        root.protocol("WM_DELETE_WINDOW", on_closing)
        ##### The image
        originalImg = Image.open(ref_image)
        if originalImg.size[0] != originalImg.size[1]:
            raise NotImplementedError("Non-square images are currently not supported. "
                                      "TODO: Make the image square by filling in black!")
        if (originalImg.mode != "L"):
            originalImg = originalImg.convert("L")
        #Scale columns to fit the maximally zoomed image size
        root.columnconfigure(0, minsize = min(int(originalImg.size[0]*7.5+1), 400))
        root.columnconfigure(1, minsize = min(int(originalImg.size[0]*7.5+1), 400))
        root.rowconfigure(3, minsize = min(int(originalImg.size[1]*15+2), 200))
        img = ImageTk.PhotoImage(originalImg)
        imgDisplay = tk.Label(root, image = img)
        imgDisplay.image = img
        imgDisplay.grid(row = 3, column = 0, columnspan=2)
        w = tk.Label(root, text = "Selected Projection Landmarks:")
        w.grid(row=0, column=2, sticky="W")
        #####
        selected={"x":None, "y":None, "nt_entry":None, "triples":[], "err":None} #Workaround for missing nonlocal in python 2
        def submitSelected():
            s=selected["nt_entry"].get()
            try:
                s=int(s)
            except:
                w = tk.Label(root, text="Please use an integer value!")
                w.grid(row = 6, column = 1, sticky ="W")
                selected["err"]=w
                selected["nt_entry"].focus_set()
            else:
                if s<1 or s>len(cg.seq):
                    w = tk.Label(root, text="The nucleotide position should be in "
                                            "the interval 1-{}.".format(len(cg.seq)))
                    w.grid(row = 6, column = 1, sticky ="W")
                    selected["err"]=w
                    selected["nt_entry"].focus_set()
                else:
                    selected["triples"].append((s, selected["x"], selected["y"]))
                    if len(selected["triples"])>=4:
                        root.destroy()
                    else:
                        w = tk.Label(root, text = "Nucleotide {} at {},{}".format(s, selected["x"],
                                                                                  selected["y"]))
                        w.grid(column=2, row = len(selected["triples"]), sticky="E")
        def updateImage():
            if selected["err"]:
                selected["err"].destroy()
                selected["err"]=None
            zoom = sc.get()
            newImg = originalImg.convert("RGB")
            for nt, x, y in selected["triples"]:
                try: #1.1.6 and above
                    newImg[x,y] = (0,150,255*nt//len(cg.seq))
                except:
                    newImg.putpixel((x,y), (0,150,255*nt//len(cg.seq)))
            if selected["x"] and selected["y"]:
                x,y = selected["x"], selected["y"]
                try: #1.1.6 and above
                    newImg[x,y] = (255,0,0)
                except:
                    newImg.putpixel((x,y), (255,0,0))
                w = tk.Label(root, text="Selected coordinates: {},{}".format(x,y))
                w.grid(row = 4, column = 0, sticky = "E")
                w = tk.Label(root, text="Please choose corresponding nucleotide\n(1-based coordinates):")
                w.grid(row = 5, column = 0, sticky = "E")
                w = tk.Entry(root)
                selected["nt_entry"] = w
                w.grid(row = 5, column = 1, sticky = "W")
                w.focus_set()
                w = tk.Button(root, text="OK", command=submitSelected)
                w.grid(row = 5, column = 1)


            newsize = (originalImg.size[0]*int(zoom), originalImg.size[1]*int(zoom))
            newImg = newImg.resize(newsize, Image.NEAREST)
            img = ImageTk.PhotoImage(newImg)
            imgDisplay.configure(image = img)
            imgDisplay.image = img
        ##### A slider for scaling the image
        l = tk.Label(root, text="Zoom:")
        l.grid(row = 0, column = 0, sticky = "E")
        def scale_img(zoom):
            updateImage()
        sc = tk.Scale(root, from_=1, to_=15, orient=tk.HORIZONTAL, command = scale_img)
        sc.grid(row = 0, column = 1, sticky = "W")
        if originalImg.size[0]<200:
            initZoom = min(15, 400//originalImg.size[0])
            sc.set(initZoom)
            updateImage()
        #The click handler for the image
        def printcoords(event):
            zoom = sc.get()
            x = int(event.x/zoom)
            y = int(event.y/zoom)
            selected["x"]=x
            selected["y"]=y
            updateImage()
        imgDisplay.bind("<Button-1>", printcoords)
        root.mainloop()
        ### We have all we need stored in selected.
        landmarks = [ tuple(x) for x in selected["triples"] ]
    return {fpp_landmarks : landmarks, fpp_scale : scale, fpp_ref_image : ref_image}

def parseCombinedEnergyString(stri, reference_cg, args, stat_source=None):
    """
    Parses an energy string, as used for the --energy commandline option
    :param stri: The combined energy string.
    :param args: The commandline arguments. A argparse.ArgumentParser instance
    :param reference_cg: The r coarse-grained RNA (e.g. a deepcopy of cg)
    :returs: A combined energy
    """
    kwargs = {}
    if args.clamp:
        kwargs["cla_pairs"] = map(operator.methodcaller("split", ","), args.clamp.split(':'))
    if args.projected_dist:
        contributions=args.projected_dist.split(":")
        kwargs["pro_distances"]={}
        for contrib in contributions:
            f=contrib.split(",")
            if len(f)!=3:
                raise ValueError("Could not parse projected-dist string: '{}'".format(contrib))
            kwargs["pro_distances"][(f[0],f[1])]=float(f[2])

    if "FPP" in stri:
        kwargs.update(getFPPArgs(cg, args))

    return fbe.energies_from_string(stri, reference_cg, args.iterations, stat_source=stat_source, **kwargs)

def energy_from_string(e, ref_cg, args, stat_source):
    if e=="D":
        return fbe.energies_from_string("ROG,AME,SLD", ref_cg)
    elif re.match("(\d+)D", e):
        match = re.match("(\d+)D", e)
        return fbe.energies_from_string("{pf}ROG,{pf}AME,{pf}SLD".format(pf=match.group(1)), ref_cg)
    elif e=="N":
        return fbe.CombinedEnergy([],[])
    else:
        return parseCombinedEnergyString(e,ref_cg, args, stat_source)

def constraint_energy_to_sm(sm, energy_string, cg, num_steps, **kwargs):
    contrib = energy_string.split(",")
    clash = []
    junction = []
    for c in contrib:
        if c in ["D","B","J"]:
            junction.append(fbe.RoughJunctionClosureEnergy())
        if c in ["D","B","C"]:
            clash.append(fbe.StemVirtualResClashEnergy())
        if c.startswith("M"):  # e.g. M8[FJC]
            pref,en = c.split("[")
            pref=float(pref[1:])
            if en[-1]!="]":
                raise ValueError("Expecting constraint energy contribution "
                                 "'{}' to end with ']'".format(c))
            en=en[:-1]
            energy = fbe.single_energy_from_string(en, cg, num_steps, **kwargs)
            if energy:
                if not hasattr(energy, "can_constrain"):
                    raise ValueError("The energy {} cannot be "
                                     "used as constraint energy!".format(energy.shortname))
                if energy.can_constrain=="junction":
                    junction.append(fbe.MaxEnergyValue(energy, pref))
                else:
                    raise NotImplementedError("can_constrain=='{}' not "
                                              "yet implemented".format(energy.can_constrain))
    sm.junction_constraint_energy=fbe.CombinedEnergy(junction)
    sm.constraint_energy=fbe.CombinedEnergy(clash)


def setup_deterministic(args):
    """
    The part of the setup procedure that does not use any call to the random number generator.

    :param args: An argparse.ArgumentParser object holding the parsed arguments.
    """
    logging.basicConfig(format="%(levelname)s:%(name)s.%(funcName)s[%(lineno)d]: %(message)s", level=logging.WARNING)
    cg, = fuc.cgs_from_args(args, nargs=1, rna_type="cg", enable_logging=True) #Set loglevel as a sideeffect
    if "s0" not in cg.defines:
        print("No sampling can be done for structures without a stem",file=sys.stderr)
        sys.exit(1)
    #Output file and directory
    ofilename=None
    if not args.eval_energy:
        if args.output_base_dir:
            if not os.path.exists(args.output_base_dir):
                os.makedirs(args.output_base_dir)
                print ("INFO: Directory {} created.".format(args.output_base_dir), file=sys.stderr)
            else:
                print ("WARNING: Using existing directory {}. Potentially overwriting its content.".format(args.output_base_dir), file=sys.stderr)

        subdir=cg.name+args.output_dir_suffix
        config.Configuration.sampling_output_dir = os.path.join(args.output_base_dir, subdir)
        if not os.path.exists(config.Configuration.sampling_output_dir):
            os.makedirs(config.Configuration.sampling_output_dir)
            print ("INFO: Directory {} created. This folder will be used for all output "
                   "files.".format(config.Configuration.sampling_output_dir), file=sys.stderr)
        else:
            print ("WARNING: Using existing directory {}. Potentially overwriting its content.".format(config.Configuration.sampling_output_dir), file=sys.stderr)

        if args.output_file:
            ofilename=os.path.join(config.Configuration.sampling_output_dir, args.output_file)

    if args.sequence_based:
        StatSourceClass = stat_container.SequenceDependentStatStorage
    else:
        StatSourceClass = stat_container.StatStorage
    #Initialize the stat_container
    if args.jar3d:
        jared_out    = op.join(config.Configuration.sampling_output_dir, "jar3d.stats")
        jared_tmp    = op.join(config.Configuration.sampling_output_dir, "jar3d")
        motifs = fma.annotate_structure(cg, jared_tmp, cg.name.split('_')[0])
        fma.print_stats_for_motifs(motifs, filename = jared_out, temp_dir = config.Configuration.sampling_output_dir )
        #Here, all stats are fallback stats for the JAR3D hits.
        new_fallbacks = [args.stats_file]
        if args.fallback_stats_files is not None:
            new_fallbacks += args.fallback_stats_files
        stat_source = StatSourceClass(jared_out, new_fallbacks)
    else:
        stat_source = StatSourceClass(args.stats_file, args.fallback_stats_files)


    if args.clustered_angle_stats:
        print("ERROR: --clustered-angle-stats is currently not implemented (and probably will be removed in the future)!", file=sys.stderr)
        sys.exit(1)

    frozen=args.freeze.split(",")
    #LOAD THE SM(s)
    if args.replica_exchange:
        sm = []
        for i in range(args.replica_exchange):
            #Initialize the spatial models
            sm.append(fbm.SpatialModel(copy.deepcopy(cg), frozen_elements=frozen))
            if args.mst_breakpoints:
                bps = args.mst_breakpoints.split(",")
                for bp in bps:
                    sm.set_multiloop_break_segment(bp)
        first_sm = sm[0]
    else:
        #Initialize the spatial model
        sm=fbm.SpatialModel(cg, frozen_elements=frozen)
        if args.mst_breakpoints:
            bps = args.mst_breakpoints.split(",")
            for bp in bps:
                sm.set_multiloop_break_segment(bp)
        first_sm = sm


    #Load the reference sm (if given)
    if args.rmsd_to:
        original_sm=fbm.SpatialModel(fuc.load_rna(args.rmsd_to, rna_type="3d", allow_many=False))
    else:
        if args.replica_exchange:
            original_sm=fbm.SpatialModel(copy.deepcopy(sm[-1].bg))
        else:
            original_sm=fbm.SpatialModel(copy.deepcopy(sm.bg))


    if original_sm.bg.defines != first_sm.bg.defines:
        raise ValueError("The RNA supplied via --rmsd-to must have "
                         "the same secondary structure as the input RNA.")

    if args.new_sampling:
        if args.constraint_energy != "D":
            raise ValueError("Cannot specify constrain energy with --new-sampling")
        if args.move_set != "Mover":
            raise ValueError("Cannot specify move-set with --new-sampling")
        args.constraint_energy = "M{}[1FJC1]".format(args.new_sampling_r_cutoff)
        if any("regular_multiloop" in sm.bg.describe_multiloop(m)
                                   for m in sm.bg.find_mlonly_multiloops()):
            args.move_set = "MoverNoRegularML:MLSegmentPairMover[{}]".format(args.new_sampling_r_cutoff)
        else:
            args.move_set = "Mover"

    # INIT ENERGY
    if args.replica_exchange:
        if "@" in args.energy:
            rep_energies = args.energy.split("@")
            if len(rep_energies) != args.replica_exchange:
                raise ValueError("Number of energies for replica exchange not correct.")
        else:
            rep_energies = [args.energy]*args.replica_exchange
        energy = []
        for e in rep_energies:
            energy.append(energy_from_string(e, original_sm.bg, args, stat_source=stat_source))
        #Initialize energies to track
        energies_to_track=[]
        if args.track_energies:
            raise ValueError("Energy tracking currently not supported for ")
        #Initialize the Constraint energies
        if "@" in args.constraint_energy:
            ce = args.constraint_energy.split("@")
        else:
            ce = [args.constraint_energy]*args.replica_exchange
        for s, c in zip(sm,ce):
            constraint_energy_to_sm(s, c, original_sm.bg, args.iterations, stat_source=stat_source)
    else:
        #Initialize the requested energies
        energy = energy_from_string(args.energy, original_sm.bg, args, stat_source=stat_source)

        #Initialize energies to track
        energies_to_track=[]
        for track_energy_string in args.track_energies.split(":"):
            if track_energy_string:
                if track_energy_string=="D":
                    energies_to_track.append(parseCombinedEnergyString("ROG,AME,SLD", cg, original_sm.bg, args, stat_source))
                else:
                    energies_to_track.append(parseCombinedEnergyString(track_energy_string, cg,
                                             original_sm.bg, args, stat_source))
        #Initialize the Constraint energies
        constraint_energy_to_sm(sm, args.constraint_energy, original_sm.bg, args.iterations, stat_source=stat_source)

    # It should not matter, which sm (in case of RE) I use for the mover,
    # as long as it corresponds to the correct bulge graph (i.e. 2D structure).
    mover = fbmov.mixed_mover_from_string(args.move_set, stat_source, original_sm)

    return sm, original_sm, ofilename, energy, energies_to_track, mover, stat_source

def setup_stat(out_file, sm, args, energies_to_track, original_sm, stat_source, save_dir=None):
    """
    Setup the stat object used for logging/ output.

    :param out_file: an opened file handle for writing
    :param sm: The spatial model. Note: A deepcopy of this object will be generated as a
               reference structure. This is unused if args.rmds_to is set.
    :param args: An argparse.ArgumentParser object holding the parsed arguments.
    """


    #stat = fbs.SamplingStatistics(original_sm, plter , None, silent=False,
    #                                  output_file=out_file,
    #                                  save_n_best = args.save_n_best,
    #                                  dists = [],
    #                                  save_iterative_cg_measures=args.save_iterative_cg_measures,
    #                                  no_rmsd = args.no_rmsd)
    #stat.step_save = args.step_save
    options={}
    if args.no_rmsd:
        options["rmsd"] = False
        options["acc"]  = False
    if args.fair_building or args.fair_building_d or args.fair_building_mst:
        args.start_from_scratch = True
    if not args.start_from_scratch and not args.rmsd_to:
        options["extreme_rmsd"] = "max" #We start at 0 RMSD. Saving the min RMSD is useless.
    options[ "step_save" ] = args.step_save
    options[ "save_n_best" ] = args.save_n_best
    options[ "save_min_rmsd" ] = args.save_min_rmsd
    options[ "measure" ]=[]
    if args.dist:
        options[ "distance" ] = list(map(str.split, args.dist.split(':'), it.repeat(","))) #map is from future!
    else:
        options[ "distance" ] = []
#    for energy in energies_to_track:
#        if  (isinstance(energy, fbe.ProjectionMatchEnergy) or
#            isinstance(energy, fbe.HausdorffEnergy)):
#                options[ "measure" ].append(energy)
    stat = sstats.SamplingStatistics(original_sm, energy_functions = energies_to_track,
                                     stat_source = stat_source,
                                     output_file=out_file, options=options,
                                     output_directory = save_dir)
    return stat

def setup_sampler(sm, energy, stat, resample, mover, stat_source, builder = fbb.Builder, new_sampling_cutoff = None):
    if not resample:
        # Build the first spatial model.
        log.info("Trying to load sampled elements...")
        loaded = fbb.load_sampled_elements(sm)
        if not loaded:
            log.warning("Could not load stats. Start with sampling of all stats.")
            resample=True

    if resample:
        log.info("Sampling all stats to build structure from scratch.")
        sm.sample_stats(stat_source)
    clashfree_builder = builder(stat_source, sm.junction_constraint_energy, sm.constraint_energy)
    clashfree_builder.accept_or_build(sm)
    clash_energies = []
    if new_sampling_cutoff is not None:
        clash_energies.append(fbe.MaxEnergyValue(
                    fbe.SampledFragmentJunctionClosureEnergy.from_cg(sm.bg,1,1,stat_source),
                    new_sampling_cutoff))
    elif sm.junction_constraint_energy is not None and len(sm.junction_constraint_energy)>0:
        clash_energies.append(sm.junction_constraint_energy)
    if sm.constraint_energy is not None and len(sm.constraint_energy)>0:
        clash_energies.append(sm.constraint_energy)
    log.info("Adding clash energies to sampler")
    energy = fbe.CombinedEnergy(energy.energies+clash_energies)
    sampler = fbs.MCMCSampler(sm, energy, mover, stat)
    return sampler

def eval_energy(sm, energy, energies_to_track):
    sm.bg.add_all_virtual_residues()
    fud.pv('energy.eval_energy(sm.bg, verbose=True, background=False)')
    if sm.constraint_energy:
        fud.pv('sm.constraint_energy.eval_energy(sm.bg, verbose=True, background=False)')
    if sm.junction_constraint_energy:
        fud.pv('sm.junction_constraint_energy.eval_energy(sm.bg, verbose=True, background=False)')
    for track_energy in energies_to_track:
        fud.pv('track_energy.eval_energy(sm.bg, verbose=True, background=False)')

def main(args):
    #Setup that does not use the random number generator.
    randstate=random.getstate()#Just for verification purposes
    sm, original_sm, ofilename, energy, energies_to_track, mover, stat_source = setup_deterministic(args)
    assert randstate==random.getstate()#Just for verification purposes
    fud.pv("energies_to_track")
    #Eval-energy mode
    if args.eval_energy:
        eval_energy(sm, energy, energies_to_track)
        sys.exit(0)

    #Set-up the random Number generator.
    #Until here, no call to random should be made.
    if args.seed:
        seed_num=args.seed
    else:
        seed_num = random.randint(0,4294967295) #sys.maxint) #4294967295 is maximal value for numpy
    random.seed(seed_num)
    np.random.seed(seed_num)

    builder = fbb.Builder

    #Main function, dependent on random.seed
    with fuc.open_for_out(ofilename, force=True) as out_file:
        # Print some information for reproducibility to the log file.
        print ("# Random Seed: {}".format(seed_num), file=out_file)
        print ("# Command: `{}`".format(" ".join(sys.argv)), file=out_file)
        label = get_version_string()
        print ("# Version: {}".format(label), file=out_file)
        if args.replica_exchange:
                print ("# Starting Replica exchange. "
                       "Please refere to the logs of the different temperature sampler.", file=out_file)
                samplers = []
                out_dirs = []
                for i in range(args.replica_exchange):
                    out_dirs.append(op.join(config.Configuration.sampling_output_dir, "temperature_{:02d}".format(i)))
                    if not os.path.exists(out_dirs[-1]):
                        os.makedirs(out_dirs[-1])

                out_files = []
                print("#NOTE: Only printing stats for first temperature to stdout. "
                      "Information for all replicas can be found in the output directory.", file=sys.stdout)
                try:
                    for i in range(args.replica_exchange):
                        out_files.append(open(op.join(out_dirs[i], "out.log"), "w"))
                    for i, e_and_s in enumerate(zip(energy, sm)):
                        r_energy, s = e_and_s
                        # Replica exchange does not support --track-energies
                        if isinstance(r_energy, fbe.CombinedEnergy):
                            energies_to_track=r_energy.energies
                        elif isinstance(r_energy, fbe.CoarseGrainEnergy):
                            energies_to_track=[r_energy]
                        stat=setup_stat(out_files[i], s, args, energies_to_track, original_sm,
                                        stat_source, save_dir=out_dirs[i])
                        if i>0: #Only have first temperature print to stdout.
                            stat.options["silent"] = True
                        for e in r_energy.iterate_energies():
                            if isinstance(e, fbe.FPPEnergy):
                                print("# Replice {} used FPP energy with options: --scale {} --ref-img {} "
                                      "--fpp-landmarks {}".format(i, e.scale, e.ref_image,
                                                              ":".join(",".join(map(str,x)) for x in e.landmarks)),
                                      file=out_file)
                        samplers.append(setup_sampler(s, r_energy, stat, resample=args.start_from_scratch, mover = mover, stat_source = stat_source, builder=builder, new_sampling_cutoff=args.new_sampling_r_cutoff))
                    try:
                        if args.parallel:
                            fbr.start_parallel_replica_exchange(samplers, args.iterations)
                        else:
                            re = fbr.ReplicaExchange(samplers)
                            re.run(args.iterations)
                    except:
                        log.exception("An error occurred during sampling:")
                        raise
                    finally:
                        for sampler in samplers:
                            sampler.stats_collector.collector.to_file()
                finally:
                    for f in out_files:
                        try:
                            f.close()
                        except:
                            pass

        elif args.fair_building or args.fair_building_d or args.fair_building_mst:
            if args.fair_building and args.fair_building_d:
                raise ValueError("--fair-building and --fair-building-d are mutually exclusive")
            if args.fair_building:
                builder = fbb.FairBuilder(stat_source, config.Configuration.sampling_output_dir, "list", sm.junction_constraint_energy, sm.constraint_energy)
                max_attempts = args.iterations*100
            elif args.fair_building_d:
                builder = fbb.DimerizationBuilder(stat_source, config.Configuration.sampling_output_dir, "list", sm.junction_constraint_energy, sm.constraint_energy)
                max_attempts = args.iterations*10
            elif args.fair_building_mst:
                builder = fbb.ChangingMSTBuilder(stat_source, config.Configuration.sampling_output_dir, "list", sm.junction_constraint_energy, sm.constraint_energy)
                max_attempts = args.iterations*100
            success, attempts, failed_mls, clashes = builder.success_probability(sm, target_structures=args.iterations, target_attempts=max_attempts, store_success = True)
            print("SUCCESS:", success, attempts, failed_mls, clashes)
            print ("{}/{} attempts to build the structure were successful ({:%}).".format(success, attempts, success/attempts)+
                   "{} times a multiloop was not closed. {} clashes occurred."
                   " Structure has {} defines and is {} nts long.".format(failed_mls, clashes, len(sm.bg.defines), sm.bg.seq_length), file=out_file)
        else: #Normal sampling
            sm.bg.to_file(os.path.join(config.Configuration.sampling_output_dir,
                      'initial.coord'))
            #Track energies without background for comparison with constituing energies
            if isinstance(energy, fbe.CombinedEnergy):
                energies_to_track+=energy.energies
            elif isinstance(energy, fbe.CoarseGrainEnergy):
                energies_to_track+=[energy]
            stat=setup_stat(out_file, sm, args, energies_to_track, original_sm, stat_source)
            try:
                for e in energy.iterate_energies():
                    if isinstance(e, fbe.FPPEnergy):
                        print("# Used FPP energy with options: --scale {} --ref-img {} "
                              "--fpp-landmarks {}".format(e.scale, e.ref_image,
                                                      ":".join(",".join(map(str,x)) for x in e.landmarks)),
                              file=out_file)
                log.info("Now setting up sampler")
                sampler = setup_sampler(sm, energy, stat, resample=args.start_from_scratch,
                                        mover = mover, stat_source = stat_source, builder=builder,
                                        new_sampling_cutoff=args.new_sampling_r_cutoff)
                for i in range(args.iterations):
                    sampler.step()
                print ("# Everything done. Terminated normally", file=out_file)
            except:
                log.exception("An error occurred during sampling:")
                raise
            finally: #Clean-up
                stat.collector.to_file()




# Parser is available even if __name__!="__main__", to allow for
# documentation with sphinxcontrib.autoprogram
parser = get_parser()
if __name__=="__main__":
    args = parser.parse_args()
    main(args)

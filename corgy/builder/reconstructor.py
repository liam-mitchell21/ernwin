import corgy.builder.loops as cbl
import corgy.builder.models as models
import corgy.builder.rmsd as brmsd

import corgy.graph.graph_pdb as cgg
import corgy.utilities.vector as cuv
import corgy.utilities.debug as cud
import corgy.utilities.pdb as cup

import corgy.builder.ccd as cbc
import corgy.aux.ccd.cytvec as cv

#import corgy.aux.Barnacle as barn
import corgy.aux.CPDB.src.examples.BarnacleCPDB as barn

import Bio.PDB as bpdb
import Bio.PDB.Chain as bpdbc
import Bio.PDB.Model as bpdbm
import Bio.PDB.Structure as bpdbs

import scipy.stats as ss

from scipy.stats import norm, poisson

import os, math, sys
import corgy.builder.config as conf
import copy, time
import random as rand

import numpy as np

def get_measurement_vectors1(ress, r1, r2):
    return( ress[r2]['C4*'].get_vector().get_array(), 
            ress[r2]['C3*'].get_vector().get_array(),
            ress[r2]['O3*'].get_vector().get_array())

def get_measurement_vectors2(ress, r1, r2):
    return( ress[r2]['O4*'].get_vector().get_array(), 
            ress[r2]['C1*'].get_vector().get_array(),
            ress[r2]['C2*'].get_vector().get_array())

def pdb_rmsd(c1, c2):
    '''
    Calculate the all-atom rmsd between two RNA chains.

    @param c1: A Bio.PDB.Chain
    @param c2: Another Bio.PDB.Chain
    @return: The rmsd between the locations of all the atoms in the chains.
    '''

    a_5_names = ['P', 'O5*', 'C5*', 'C4*', 'O4*', 'O2*']
    a_3_names = ['C1*', 'C2*', 'C3*', 'O3*']

    a_names = dict()
    a_names['U'] = a_5_names + ['N1', 'C2', 'O2', 'N3', 'C4', 'O4', 'C5', 'C6'] + a_3_names
    a_names['C'] = a_5_names + ['N1', 'C2', 'O2', 'N3', 'C4', 'N4', 'C5', 'C6'] + a_3_names

    a_names['A'] = a_5_names + ['N1', 'C2', 'N3', 'C4', 'C5', 'C6', 'N6', 'N7', 'C8', 'N9'] + a_3_names
    a_names['G'] = a_5_names + ['N1', 'C2', 'N2', 'N3', 'C4', 'C5', 'C6', 'O6', 'N7', 'C8', 'N9'] + a_3_names

    all_atoms1 = []
    all_atoms2 = []

    if len(c1.get_list()) != len(c2.get_list()):
        print >>sys.stderr, "Chains of different length"
        raise Exception("Chains of different length.")

    for i in range(1, len(list(c1.get_list()))+1):
        anames = a_5_names + a_names[c1[i].resname.strip()] + a_3_names
        #anames = a_5_names + a_3_names

        try:
            atoms1 = [c1[i][a] for a in anames]
            atoms2 = [c2[i][a] for a in anames]
        except KeyError:
            print >>sys.stderr, "Residue number %d is missing an atom, continuing with the rest." % (i)
            continue

        if len(atoms1) != len(atoms2):
            print >>sys.stderr, "Number of atoms differs in the two chains."
            raise Exception("Missing atoms.")

        all_atoms1 += atoms1
        all_atoms2 += atoms2

    print "rmsd len:", len(all_atoms1), len(all_atoms2)
    sup = bpdb.Superimposer()
    sup.set_atoms(all_atoms1, all_atoms2)

    return sup.rms

def rotate_stem(stem, (u, v, t)):
    '''
    Rotate a particular stem.
    '''
    stem2 = copy.deepcopy(stem)
    rot_mat4 = models.get_stem_rotation_matrix(stem, (u,v,t))
    stem2.rotate(rot_mat4, offset=stem.mids[0])

    return stem2

def reconstruct_stems(sm, stem_library=dict()):
    '''
    Reconstruct the stems around a Spatial Model.

    @param sm: Spatial Model
    '''
    #sm.traverse_and_build()
    new_chain = bpdbc.Chain(' ')

    for stem_name in sm.stem_defs.keys():
        models.reconstruct_stem(sm, stem_name, new_chain, stem_library)

    return new_chain

def output_chain(chain, filename, fr=None, to=None):
    '''
    Dump a chain to an output file.

    @param chain: The Bio.PDB.Chain to dump.
    @param filename: The place to dump it.
    '''
    m = bpdbm.Model(' ')
    s = bpdbs.Structure(' ')

    m.add(chain)
    s.add(m)

    io = bpdb.PDBIO()
    io.set_structure(s)
    io.save(filename)

def splice_stem(chain, define):
    '''
    Extract just the defined stem from the chain and return it as
    a new chain.
    
    @param chain: A Bio.PDB.Chain containing the stem in define
    @param define: The BulgeGraph stem define
    '''
    start1 = define[0]
    end1 = define[1]

    start2 = define[2]
    end2 = define[3]

    new_chain = bpdbc.Chain(' ')

    for i in xrange(start1, end1+1):
        #new_chain.insert(i, chain[i])
        new_chain.add(chain[i])

    for i in xrange(start2, end2+1):
        new_chain.add(chain[i])

    '''
    m = Model(' ')
    s = Structure(' ')
    m.add(new_chain)
    s.add(m)

    io=PDBIO()
    io.set_structure(s)
    io.save('temp.pdb')
    '''

    return new_chain

def print_alignment_pymol_file(handles):
    output_str = """
select bb, /s2///%d/O4* | /s2///%d/C1* | /s2///%d/C1*
show sticks, bb
color red, bb

select bb, /s2///%d/O4* | /s2///%d/C1*| /s2///%d/C2*
show sticks, bb
color red, bb

select bb, s1///%d/O4* | s1///%d/C1* | s1///%d/C2*
show sticks, bb
color green, bb

select bb, s1///%d/O4* | s1///%d/C1* | s1///%d/C2*
show sticks, bb
color green, bb

show cartoon, all
""" % (handles[2], handles[2], handles[2],
        handles[3], handles[3], handles[3],
        handles[0], handles[0], handles[0],
        handles[1], handles[1], handles[1])
    output_file = os.path.join(conf.Configuration.test_output_dir, "align.pml")
    f = open(output_file, 'w')
    f.write(output_str)
    f.flush()
    f.close()

def get_flanking_stem_vres_distance(bg, ld):
    '''
    Get the distance between the two virtual residues adjacent
    to this bulge region.

    @param bg: The BulgeGraph data structure
    @param ld: The name of the linking bulge
    '''

    if len(bg.edges[ld]) == 2:
        connecting_stems = list(bg.edges[ld])

        (s1b, s1e) = bg.get_sides(connecting_stems[0], ld)
        (s2b, s2e) = bg.get_sides(connecting_stems[1], ld)

        if s1b == 1:
            (vr1_p, vr1_v) = cgg.virtual_res_3d_pos(bg, connecting_stems[0], bg.stem_length(connecting_stems[0]) - 1)
        else:
            (vr1_p, vr1_v) = cgg.virtual_res_3d_pos(bg, connecting_stems[0], 0)

        if s2b == 1:
            (vr2_p, vr2_v) = cgg.virtual_res_3d_pos(bg, connecting_stems[1], bg.stem_length(connecting_stems[1]) - 1)
        else:
            (vr2_p, vr2_v) = cgg.virtual_res_3d_pos(bg, connecting_stems[1], 0)

        dist2 = cuv.vec_distance((vr1_p + 7 * vr1_v), (vr2_p + 7. * vr2_v))
    else:
        dist2 = 0.

    return dist2

def reconstruct_loop(chain, sm, ld, side=0, samples=40, consider_contacts=True):
    '''
    Reconstruct a particular loop.

    The chain should already have the stems reconstructed.

    @param chain: A Bio.PDB.Chain structure.
    @param sm: A SpatialModel structure
    @param ld: The name of the loop
    '''
    #samples = 2
    bg = sm.bg
    seq = bg.get_flanking_sequence(ld, side)
    (a,b,i1,i2) = bg.get_flanking_handles(ld, side)

    # get some diagnostic information
    bl = abs(bg.defines[ld][side * 2 + 1] - bg.defines[ld][side * 2 + 0])
    dist = cuv.vec_distance(bg.coords[ld][1], bg.coords[ld][0])
    dist2 = get_flanking_stem_vres_distance(bg, ld)

    sys.stderr.write("reconstructing %s ([%d], %d, %f, %f):" % (ld, len(bg.edges[ld]), bl, dist, dist2))
    best_loop_chain = cbl.build_loop(chain, seq, (a,b,i1,i2), bg.length, samples)

    output_chain(chain, os.path.join(conf.Configuration.test_output_dir, 's1.pdb'))
    output_chain(best_loop_chain, os.path.join(conf.Configuration.test_output_dir, 's2.pdb'))
    print_alignment_pymol_file((a,b,i1,i2))

    cup.trim_chain(best_loop_chain, i1, i2+1)
    cbl.add_loop_chain(chain, best_loop_chain, (a,b,i1,i2), bg.length)
    sys.stderr.write('\n')
    sys.stderr.flush()

def reconstruct_loops(chain, sm, samples=40, consider_contacts=False):
    '''
    Reconstruct the loops of a chain.

    All of the stems should already be reconstructed in chain.

    @param chain: A Bio.PDB.Chain chain.
    @param sm: The SpatialModel from which to reconstruct the loops.
    '''
    for d in sm.bg.defines.keys():
        if d[0] != 's':
            if sm.bg.weights[d] == 2:
                reconstruct_loop(chain, sm, d, 0, samples=samples, consider_contacts=consider_contacts)
                reconstruct_loop(chain, sm, d, 1, samples=samples, consider_contacts=consider_contacts)
            else:
                reconstruct_loop(chain, sm, d, 0, samples=samples, consider_contacts=consider_contacts)
            

def reconstruct(sm):
    '''
    Re-construct a full-atom model from a coarse-grain model.

    @param bg: The BulgeGraph
    @return: A Bio.PDB.Chain chain
    '''
    chain = reconstruct_stems(sm)
    reconstruct_loops(chain, sm)
    return chain

def replace_base(res_dir, res_ref):
    '''
    Orient res_ref so that it points in the same direction
    as res_dir.

    @param res_dir: The residue indicating the direction
    @param res_ref: The reference residue to be rotated
    @return res: A residue with the atoms of res_ref pointing in the direction of res_dir
    '''
    #av = { 'U': ['N1', 'C6', 'C2'], 'C': ['N1', 'C6', 'C2'], 'A': ['N9', 'C4', 'C8'], 'G': ['N9', 'C4', 'C8'] }
    av = { 'U': ['N1', 'C1*', 'C2*'], 'C': ['N1', 'C1*', 'C2*'], 'A': ['N9', 'C1*', 'C2*'], 'G': ['N9', 'C1*', 'C2*'] }

    dv = av[res_dir.resname.strip()]
    rv = av[res_ref.resname.strip()]

    dir_points = np.array([res_dir[v].get_vector().get_array() for v in dv])
    ref_points = np.array([res_ref[v].get_vector().get_array() for v in rv])

    dir_centroid = cuv.get_vector_centroid(dir_points)
    ref_centroid = cuv.get_vector_centroid(ref_points)

    #sup = brmsd.optimal_superposition(dir_points - dir_centroid, ref_points - ref_centroid)
    sup = brmsd.optimal_superposition(ref_points - ref_centroid, dir_points - dir_centroid)
    new_res = copy.deepcopy(res_ref)

    for atom in new_res:
        atom.transform(np.eye(3,3), -ref_centroid)
        atom.transform(sup, dir_centroid)

    #print "dir_points:", dir_points
    #print "ref_points:", ref_points
    return new_res

def replace_bases(chain, seq):
    '''
    Go through the chain and replace the bases with the ones specified in the
    sequence.

    This is necessary since the stems are sampled by their length rather than
    sequence. Therefore some stem fragments may contain a sequence that is
    different from the one that is required.

    This method will change the identity of those bases, as well as align the atoms
    according to their N1->C2, N1->C6 or N9->C4, N9->C8. vector pairs.

    param @chain: A Bio.PDB.Chain with some reconstructed residues
    param @seq: The sequence of the structure represented by chain
    '''
    s1 = bpdb.PDBParser().get_structure('t', conf.Configuration.template_residue_fn)
    tchain = list(s1.get_chains())[0]


    tindeces = { 'A': 1, 'C': 2, 'G': 3, 'U': 4}

    print "len(seq):", len(seq)
    ress = chain.get_list()

    for i in range(len(ress)):
        num = ress[i].id[1]
        name = ress[i].resname.strip()

        ref_res = tchain[tindeces[seq[num-1]]]
        new_res = replace_base(ress[i], ref_res)

        sca = side_chain_atoms[ress[i].resname.strip()]
        for aname in sca:
            ress[i].detach_child(aname)
        
        sca = side_chain_atoms[new_res.resname.strip()]
        for aname in sca:
            ress[i].add(new_res[aname])

        ress[i].resname = new_res.resname
        '''
        ress[i].resname = new_res.resname
        ress[i].child_list = new_res.child_list
        ress[i].child_dict = new_res.child_dict
        '''

        

#!/usr/bin/python

from Bio.PDB import PDBParser, Vector
from sys import argv

from numpy import array
from numpy.linalg import inv
from numpy.testing import assert_allclose

from corgy.utilities.vector import dot, cross, vector_rejection, magnitude, normalize
from corgy.utilities.vector import change_basis, create_orthonormal_basis
from corgy.utilities.vector import spherical_cartesian_to_polar, rotation_matrix
from corgy.utilities.vector import spherical_polar_to_cartesian
from corgy.utilities.vector import get_vector_centroid
from corgy.utilities.vector import standard_basis

from math import pi, atan2, cos, sin

catom_name = 'C1*'


def get_stem_phys_length(coords):
    '''
    Return the physical length of a stem.

    @param coords: The coordinates of the ends of the helix axis.
    '''

    return magnitude(coords[1] - coords[0])

def get_twist_angle(coords, twists):
    ''' 
    Get the angle of the twists with respect to each other.

    @param coords: The coordinates of the ends of the stem.
    @param twists: The two twist vectors.
    @return angle: The angle between the two twist vectors.
    '''

    stem_vec = coords[1] - coords[0]
    basis = create_orthonormal_basis(stem_vec, twists[0])

    twist2 = change_basis(twists[1], basis, standard_basis)
    #assert_allclose(twist2[0], 0., rtol=1e-7, atol=1e-7)

    angle = atan2(twist2[2], twist2[1])
    return angle

def twist2_from_twist1(stem_vec, twist1, angle):
    '''
    Get an orientation for the second twist which will place it an
    angle of angle from the first twist.

    @param stem_vec: The vector of the stem.
    @param twist1: The vector of the first twist.
    @param angle: The angular difference between the two twists.
    '''
    basis = create_orthonormal_basis(stem_vec, twist1)

    twist2_new = array([0., cos(angle), sin(angle)])
    twist2 = change_basis(twist2_new, standard_basis, basis)

    return twist2

def get_twist_parameter(twist1, twist2, (u, v)):
    '''
    Calculate how much stem1 must be twisted for its twist vector
    to coincide with that of stem2.

    @param twist1: The twist notator of stem1
    @param twist2: The twist notator of stem2
    @param (u,v): The parameters for rotating stem2 onto stem1
    '''

    rot_mat1 = rotation_matrix(standard_basis[2], v)
    rot_mat2 = rotation_matrix(standard_basis[1], u - pi/2)

    twist2_new = dot(rot_mat1, twist2)
    twist2_new = dot(rot_mat2, twist2_new)
    
    #print "get_twist_parameter twist2:", twist2_new

    return atan2(twist2_new[2], twist2_new[1])

    

def get_stem_orientation_parameters(stem1_vec, twist1, stem2_vec, twist2):
    '''
    Return a parameterization of the orientation of stem2 with respect to stem1.

    stem1 -> bulge -> stem2

    @param stem1_vec: The vector representing the axis of stem1
    @param twist1: The twist of stem1 closest to the bulge
    @param stem2_vec: The vector representing teh axis of stem2
    '''

    # Since we will denote the orientation of stem2 with respect to stem1
    # We first need to define a new coordinate system based on stem1

    stem1_basis = create_orthonormal_basis(stem1_vec, twist1)

    # Transform the vector of stem2 to the new coordinate system
    stem2_new_basis = change_basis(stem2_vec, stem1_basis, standard_basis) 
    twist2_new_basis = change_basis(twist2, stem1_basis, standard_basis)

    # Convert the cartesian coordinates to polar coordinates
    (r, u, v) = spherical_cartesian_to_polar(stem2_new_basis)
    t = get_twist_parameter(twist1, twist2_new_basis, (u, v))

    return (r, u, v, t)


def get_stem_separation_parameters(stem, twist, bulge):
    '''
    Parameterize the location of the bulge with respect to the stem.

    @param stem: The stem vector.
    @param bulge: the bulge vector.
    '''

    stem_basis = create_orthonormal_basis(stem, twist)
    bulge_new_basis = change_basis(bulge, stem_basis, standard_basis)

    return spherical_cartesian_to_polar(bulge_new_basis)


def get_stem_twist_and_bulge_vecs(bg, bulge, connections):
    '''
    Return the vectors of the stems and of the twists between which
    we want to calculate angles.

    The two vectors will be defined as follows:

    s1e -> s1b -> b -> s2b -> s2e

    The twists will be the two closest to the bulge.

    @param bulge: The name of the bulge separating the two helices.
    @param connections: The two stems that are connected to this bulge.
    @return: (stem1, twist1, stem2, twist2, bulge)
    '''

    s1 = connections[0]
    s2 = connections[1]

    #s1d = bg.defines[s1]
    #s2d = bg.defines[s2]

    mids1 = bg.coords[s1]
    twists1 = bg.twists[s1]

    mids2 = bg.coords[s2]
    twists2 = bg.twists[s2]

    # find out which sides of the stems are closest to the bulge
    # the results will be indexes into the mids array
    (s1b, s1e) = bg.get_sides(s1, bulge)
    (s2b, s2e) = bg.get_sides(s2, bulge)

    # Create directional vectors for the stems
    stem1_vec = mids1[s1b] - mids1[s1e]
    bulge_vec = mids2[s2b] - mids1[s1b]
    stem2_vec = mids2[s2e] - mids2[s2b]

    #twists1_vec = [twists1[s1b], twists1[s1e]]
    #twists2_vec = [twists2[s2e], twists2[s2b]]

    return (stem1_vec, twists1[s1b], stem2_vec, twists2[s2b], bulge_vec)

def stem2_pos_from_stem1(stem1, twist1, params):
    '''
    Get the starting point of a second stem, given the parameters
    about where it's located with respect to stem1

    @param stem1: The vector representing the axis of stem1's cylinder
    @param twist1: The twist parameter of stem1
    @param params: The parameters describing the orientaiton of stem2 wrt stem1
    '''
    (r, u, v) = params
    stem2 = spherical_polar_to_cartesian((r, u, v))

    stem1_basis = create_orthonormal_basis(stem1, twist1)
    stem2_start = change_basis(stem2, standard_basis, stem1_basis)

    return stem2_start

def twist2_orient_from_stem1(stem1, twist1, (u, v, t)):
    '''
    Calculate the position of the twist factor of the 2nd stem from its
    parameters and the first stem.

    @param stem1: The vector representing the axis of stem1's cylinder
    @param twist1: The twist factor of stem1.
    @param (u, v, t): The parameters describing how the twist of stem2 is oriented with respect to stem1
    '''

    twist2_new = array([0., cos(t), sin(t)])

    rot_mat1 = rotation_matrix(standard_basis[2], v)
    rot_mat2 = rotation_matrix(standard_basis[1], u - pi/2)

    rot_mat = dot(rot_mat2, rot_mat1)
    twist2_new = dot(inv(rot_mat), twist2_new)
    
    '''
    twist2_new = dot(inv(rot_mat2), twist2_new)
    twist2_new = dot(inv(rot_mat1), twist2_new)
    '''

    stem1_basis = create_orthonormal_basis(stem1, twist1)
    twist2_new_basis = change_basis(twist2_new, standard_basis, stem1_basis)

    return twist2_new_basis

def stem2_orient_from_stem1(stem1, twist1, (r, u, v)):
    '''
    Calculate the orientation of the second stem, given its parameterization
    and the parameterization of stem1

    @param stem1: The vector representing the axis of stem1's cylinder
    @param twist1: The twist factor of stem1.
    @param (r,u,v): The orientation of stem2 wrt stem1
    '''
    stem2 = spherical_polar_to_cartesian((r, u, v))
    stem1_basis = create_orthonormal_basis(stem1, twist1)
    stem2 = change_basis(stem2, standard_basis, stem1_basis)

    return stem2

def get_centroid(chain, residue_num):
    residue_num = [int(i) for i in residue_num]
    #print >>sys.stderr, "residue_num:", residue_num
    atoms = []
    for i in residue_num:
        try:
            atoms += [chain[i]['C1*']]
        except KeyError:
            # the C1* atom probably doesn't exist
            continue

    vectors = [atom.get_vector().get_array() for atom in atoms]

    return get_vector_centroid(vectors)

def get_bulge_centroid(chain, define):
    i = 0
    res_nums = []
    while i < len(define):
        res_nums += range(int(define[i]), int(define[i+1])+1)
        i += 2

    #print >>sys.stderr, "res_nums:", res_nums
    return get_centroid(chain, res_nums)

def get_mids_core(chain, start1, start2, end1, end2):
    '''
    Get the start and end points of a helix.
    '''
    #assert(abs(end1 - start1) == abs(end2 - start2))

    fragment_length = end1 - start1 + 1

    #print "start1:", start1, "end1:", end1, "fragment_length:", fragment_length
    if fragment_length < 2:
        raise Exception("Helix shorter than 1 nucleotide")

    # get the vector between the CA atoms of the two starting residues
    # as well as for the two next residues
    start_vec1 = chain[start1][catom_name].get_vector() - chain[start2][catom_name].get_vector()
    end_vec1 = chain[end1][catom_name].get_vector() - chain[end2][catom_name].get_vector()

    # get the vector between the CA atoms of the two ending residues
    # as  well as for the two previous residues
    start_vec2 = chain[start1+1][catom_name].get_vector() - chain[start2-1][catom_name].get_vector()
    end_vec2 = chain[end1-1][catom_name].get_vector() - chain[end2+1][catom_name].get_vector()


    # a vector kind of pointing in the direction of the helix
    start_norm_vec = Vector(cross(start_vec1.get_array(), start_vec2.get_array()))
    start_norm_vec.normalize()

    # another vector kind of pointing in the directions of the helix
    end_norm_vec = Vector(cross(end_vec2.get_array(), end_vec1.get_array()))
    end_norm_vec.normalize()

    start_vec1 = -start_vec1
    end_vec1 = -end_vec1

    # I guess we're converting them to Vector format in a weird sort of way...
    # otherwise these steps don't really make sense
    start_axis_vec = start_vec1 + Vector([0.,0.,0.])
    start_axis_vec.normalize()
    
    end_axis_vec = end_vec1 + Vector([0.,0.,0.])
    end_axis_vec.normalize()

    start_origin = chain[start1][catom_name].get_vector()
    end_origin = chain[end1][catom_name].get_vector()

    start_y_vec = Vector(cross(start_norm_vec.get_array(), start_axis_vec.get_array()))
    start_y_vec.normalize()
    start_c_vec = (start_axis_vec + start_y_vec) / 2
    start_c_vec.normalize()
    start_c_norm = start_origin + start_c_vec / (1 / 8.4)

    end_y_vec = Vector(cross(end_norm_vec.get_array(), end_axis_vec.get_array()))
    end_y_vec.normalize()
    end_c_vec = (end_axis_vec + end_y_vec) / 2
    end_c_vec.normalize()
    end_c_norm = end_origin + end_c_vec / (1 / 8.4)


    mid1 = start_c_norm
    mid2 = end_c_norm


    #print " CYLINDER, %f, %f, %f, %f, %f, %f, 1.8, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0," % (mid1[0], mid1[1], mid1[2], mid2[0], mid2[1], mid2[2])
    helix_vector = mid2 - mid1
    #helix_vector.normalize()

    return (mid1, mid2)

def get_twists_core(chain, start1, start2, end1, end2):
    '''
    Get the vectors indicating the twist of the cylinder. In actuality, this will
    be the projection of the (ca_start1 - mid1) onto the plane defined by (mid2 - mid1).
    '''

    mids = get_mids_core(chain, start1, start2, end1, end2)

    '''
    start_vec1 = chain[start1][catom_name].get_vector() - chain[start2][catom_name].get_vector()
    end_vec1 = chain[end1][catom_name].get_vector() - chain[end2][catom_name].get_vector()

    '''
    start_vec1 = chain[start1][catom_name].get_vector() - mids[0]
    end_vec1 = chain[end1][catom_name].get_vector() - mids[1]

    #print >>sys.stderr, "mag1:", magnitude(start_vec1)
    #print >>sys.stderr, "mag2:", magnitude(end_vec1)

    notch1 = vector_rejection(start_vec1.get_array(), (mids[0] - mids[1]).get_array())
    notch2 = vector_rejection(end_vec1.get_array(), (mids[1] - mids[0]).get_array())

    return (normalize(notch1), normalize(notch2))


def get_mids(chain, define):
    '''
    Get the mid points of the abstract cylinder which represents a helix.

    @param chain: The Bio.PDB representation of the 3D structure.
    @param define: The define of the helix, as per the BulgeGraph definition standard.
    @return: An array of two vectors representing the two endpoints of the helix.
    '''

    return get_mids_core(chain, int(define[0]), int(define[3]), int(define[1]), int(define[2]))

def get_twists(chain, define):
    '''
    Get the projection of the (ca - mids) vectors onto the helix axis. This, in a sense
    will define how much the helix twists.

    @param chain: The Bio.PDB representation of the 3D structure.
    @param define: The define of the helix, as per the BulgeGraph definition standard.
    @return: Two vectors which represent the twist of the helix.
    '''

    return get_twists_core(chain, int(define[0]), int(define[3]), int(define[1]), int(define[2]))

def get_helix_vector(chain, start1, start2, end1, end2):
    (mid1, mid2) = get_mids(chain, start1, start2, end1, end2)
    return mid2 - mid1

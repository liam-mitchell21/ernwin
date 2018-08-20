#!/usr/bin/python
from __future__ import absolute_import, division, print_function, unicode_literals
from builtins import (ascii, bytes, chr, dict, filter, hex, input, #pip install future
                      int, map, next, oct, open, pow, range, round,
                      str, super, zip)
__metaclass__=object

from collections import defaultdict, Counter
import random
import warnings
import os.path as op
import os
import pkgutil as pu

import math
import re
import sys
import inspect
import itertools
from pprint import pprint
import logging
import time
if sys.version_info>=(3,):
    from io import StringIO
else:
    from StringIO import StringIO


import numpy as np
import scipy.stats
import scipy.optimize
import scipy.ndimage
import scipy.misc
import pandas as pd

import Bio.KDTree as kd #KD-Trees for distance-calculations in point-cloud.

from logging_exceptions import log_to_exception

import forgi.threedee.utilities.vector as ftuv
import forgi.threedee.model.coarse_grain as ftmc
import forgi.threedee.utilities.graph_pdb as ftug
import forgi.projection.projection2d as fpp
import forgi.projection.hausdorff as fph
import forgi.threedee.model.similarity as ftms
import forgi.threedee.model.descriptors as ftmd


from .energy_abcs import EnergyFunction, CoarseGrainEnergy, DEFAULT_ENERGY_PREFACTOR
import fess.builder.aminor as fba
from fess.builder._commandline_helper import replica_substring
from ..utils import get_all_subclasses, get_version_string

log = logging.getLogger(__name__)


try:
  profile  #The @profile decorator from line_profiler (kernprof)
except:
  def profile(x):
    return x

INCR = 0.01


def load_local_data(filename):
    '''
    Load a data file that is located within this
    package.

    An example is something like 'stats/longrange.stats'.

    :param: A filename relative to the base directory of the package.
    :return: A StriungIO stream.
    '''
    data = pu.get_data('fess', filename)
    try: # Py 2K
        return StringIO(data)
    except TypeError:
        return StringIO(data.decode("utf-8"))

class RandomEnergy(EnergyFunction):
    _shortname = "RND"
    HELPTEXT = "Random Energy"
    def eval_energy(self, cg, background=None, nodes=None, **kwargs):
        return self.prefactor * random.random() + self.adjustment

class ConstantEnergy(EnergyFunction):
    _shortname = "CNST"
    HELPTEXT = "Constant Energy"
    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        if adjustment is not None:
            warnings.warn("Adjustment {} ignored for constant energy CNST".format(adjustment))
        return cls(prefactor)

    def __init__(self, value = 0):
        super(ConstantEnergy, self).__init__(prefactor = value)
    def eval_energy(self, cg, background=None, nodes=None, **kwargs):
        return self.prefactor + self.adjustment

class CheatingEnergy(EnergyFunction):
    _shortname = "CHE"
    HELPTEXT = "Cheating Energy. Tries to minimize the RMSD."
    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        return cls(cg, prefactor, adjustment)
    def __init__(self, ref_cg, prefactor = None, adjustment = None):
        """
        The energy is RMSD**adjustment*prefactor
        """
        super(CheatingEnergy, self).__init__(prefactor = prefactor, adjustment = adjustment)
        self.real_residues = ftug.bg_virtual_residues(ref_cg)
    def eval_energy(self, cg, background=None, nodes=None, **kwargs):
        new_residues = ftug.bg_virtual_residues(cg)
        return  ftms.rmsd(self.real_residues, new_residues)**self.adjustment*self.prefactor

class ProjectionMatchEnergy(EnergyFunction):
    _shortname = "PRO"
    HELPTEXT = ("Match Projection distances. \n"
               "Requires the projected distances.")
    @classmethod
    def from_cg(cls, prefactor, adjustment, pro_distances, cg, **kwargs):
        """
        :param pro_distances: A dictionary tuple(str,str):float that maps pairs
                              of element names to distances in the projected plane (in Angstrom)
        """
        if adjustment is not None:
            warnings.warn("Adjustment {} ignored for PRO energy".format(adjustment))
        return cls(pro_distances, prefactor)

    def __init__(self, distances={}, prefactor=None):
        """
        :param directions: A dict where the keys are tuples of coarse grain element names
                           (e.g.: ("h1","m1")) and the values are the distance
                           IN THE PROJECTED PLANE (i.e. in the micrograph).
        """
        if prefactor is None:
            prefactor = 1.
        super(ProjectionMatchEnergy, self).__init__(prefactor = prefactor)
        self.distances=distances
        #: The optimal projection direction for the last accepted step.
        self.accepted_projDir=np.array([1.,1.,1.])
        self.projDir=np.array([1.,1.,1.])
        self.start_points=self._get_start_points(60)
    def _get_start_points(self, numPoints):
        """
        Return numPoints equally-distributed points on half the unit sphere.

        Implements the 2nd algorithm from https://www.cmu.edu/biolphys/deserno/pdf/sphere_equi.pdf
        """
        numPoints=2*numPoints
        a=4*math.pi/numPoints
        d=math.sqrt(a)
        Mt=int(math.pi/d)
        dt=math.pi/Mt
        df=a/dt
        points=[]
        for m in range(Mt):
            theta=math.pi*(m+0.5)/Mt
            Mf=int(2*math.pi*math.sin(theta)/df)
            for n in range(Mf):
                phi=2*math.pi*n/Mf
                points.append((math.sin(theta)*math.cos(theta),
                               math.sin(theta)*math.sin(phi),
                               math.cos(theta)))
        return [np.array(p) for p in points if p[0]>=0]

    def optimizeProjectionDistance(self, p):
        """
        :param c: A numpy array. The projection vector that HAS TO BE NORMALIZED

        Let theta be the angle between the p, normal vector of the plane of projection,
        and the vector a which is projected onto that plain.
        Then dist_2d=dist_3d*cos(alpha)=dist_3d*cos(90 degrees-theta)
        Then the angle theta is given by: cos(theta)=a*p/len(a) if p is normalized.
        Then dist_2d=dist_3d*sqrt(1-(a*p/len(a))^2)
        This means dist_2d^2=dist3d^2*(1-(a*p/len(a))^2)
        And dist_3d^2-dist2d^2=(a*p/len(a))^2 (Eq.1)
        We now search for the projection angle p which best generates the projected
        lengths given the current 3D structure.
        In the optimal case, Eq 1 holds for some values of p for all vectors a.
        In the suboptimal case, there is a squared deviation d:
        d=(a*p/len(a))^2-(dist_3d^2-dist2d^2)
        We want to minimize the sum over all square deviations for all distances
        considered in this energy function.
        minimize sum(d)=sum((a*p/len(a))^2-(dist_3d^2-dist2d^2)) with respect to p
        for all d, i.e. for all a, dist_3d, dist_2d considered.
        Under the side constraint that p has to be normalized.
        """
        x=0
        #Sum over all given distances
        for (s,e), dist in self.distances.items():
            sc=self.cg.coords[s]
            ec=self.cg.coords[e]
            #The middle point of the cg element
            start=(sc[0]+sc[1])/2
            end=(ec[0]+ec[1])/2
            a=end-start
            lengthDifferenceExperiment=ftuv.magnitude(a)**2-dist**2
            lengthDifferenceGivenP=(p[0]*a[0]+p[1]*a[1]+p[2]*a[2])**2
            # Add the deviation between (3d length-2d length)**2 observed vs calculated
            # for the given projection angle
            x+=abs(lengthDifferenceGivenP-lengthDifferenceExperiment)
        return x

    def eval_energy(self, cg, background=None, nodes=None, **kwargs):
        """
        Returns a measure that is zero for a perfect fit with the target
        projection distances and increases as the fit gets worse.

        This function tries to minimize its value over all projection directions.
        A global optimization is attempted and we are only interested in projection directions
        from the origin to points on half the unit sphere. Thus we first sample the energy for
        multiple, equally distributed directions. From the best one we operform a local optimization.

        For our specific purpose, where our starting points can give a good overview over
        the landscape, this is better and faster than more sophisticated
        global optimization techniques.
        """
        self.cg=cg
        # The projection vector has to be normalized
        c1={'type':'eq', 'fun':lambda x: x[0]**2+x[1]**2+x[2]**2-1}
        best_start=np.array([0.,0.,0.])
        best_score=float('inf')
        for direction in self.start_points:
            score=self.optimizeProjectionDistance(direction)
            if score<best_score:
                best_start=direction
                best_score=score
        opt=scipy.optimize.minimize(self.optimizeProjectionDistance, direction,
                                    constraints=c1, options={"maxiter":200} )
        if opt.success:
            self.projDir=opt.x
            score = math.sqrt(opt.fun)/len(self.distances)
            self._last_measure = score
            return self.prefactor*score
        else:
            self._last_measure = 10**11
            return 10**11

    def accept_last_measure(self):
        super(ProjectionMatchEnergy, self).accept_last_measure()
        self.accepted_projDir=self.projDir

class FPPEnergy(EnergyFunction):
    _shortname = "FPP"
    name = "Four-Point-Projection-Energy"
    HELPTEXT = ("4 point projection energy.\n"
                "Select 4 landmarks in the projected image.")

    @classmethod
    def from_cg(cls, prefactor, adjustment, fpp_landmarks, fpp_ref_image, fpp_scale, cg, **kwargs):
        """
        :param fpp_ref_image: The path to the reference image
        :param fpp_landmarks: A list of 3-tuples (residue_num, x (in pixels), y (in pixels))
        :param fpp_scale: The width of the image in Angstrom
        """
        if adjustment is not None:
            warnings.warn("Adjustment {} ignored for FPP energy".format(adjustment))
        return cls(prefactor, fpp_landmarks, fpp_scale, fpp_ref_image)
    def __init__(self, pre, landmarks, scale, ref_image):
        super(FPPEnergy, self).__init__(prefactor = pre)
        self.landmarks = landmarks
        self.scale = scale
        self.ref_image = fpp.to_grayscale(scipy.ndimage.imread(ref_image))

    @profile
    def eval_energy(self, cg, background=True, nodes=None, **kwargs):
        steplength = self.scale/self.ref_image.shape[0]
        ### Step 1: Calculate projection direction:
        vectors3d, angles, penalties = self._generate_equations(cg)
        a = np.array(vectors3d[:3])
        b = np.array(angles[:3])
        #Solve the equation system ax = b
        try:
            projection_direction = np.linalg.solve(a, b)
        except Exception as e: #Degenerate equations. Estimate the solution from full set of equations
            log.info("{}: USING LSTSQ".format(e), exc_info=True)
            projection_direction = np.linalg.lstsq(np.array(vectors3d), np.array(angles))[0] #lstsq instead of solve, because system may be underdetermined

        ###
        #sm.bg.project_from = ftuv.normalize(-projection_direction)
        #proj =  fpp.Projection2D(sm.bg, project_virtual_atoms = "selected")
        #orig_img, _ = proj.rasterize(self.ref_image.shape[0], warn = False)
        proj, angleA, offset_centroidA, bs = self._find_offset(cg, projection_direction, mirror = True)
        img1, _ = proj.rasterize(self.ref_image.shape[0], bs, rotate = math.degrees(angleA), warn = False, virtual_residues = False)
        scoreA = fph.combined_distance(img1, self.ref_image)
        proj, angleB, offset_centroidB, bs = self._find_offset(cg, projection_direction, mirror = False)
        img2, _ = proj.rasterize(self.ref_image.shape[0], bs, rotate = math.degrees(angleB), warn = False, virtual_residues = False)
        scoreB = fph.combined_distance(img2, self.ref_image)
        if scoreA<scoreB:
            cg.project_from = ftuv.normalize(-projection_direction)
            score, img, params = fph.locally_minimal_distance(self.ref_image, self.scale, cg,
                                                          math.degrees(angleA), offset_centroidA,
                                                          None, distance=fph.combined_distance,
                                                          maxiter=200, virtual_atoms="selected")
        else:
           score, img, params = fph.locally_minimal_distance(self.ref_image, self.scale, cg,
                                                         math.degrees(angleB), offset_centroidB,
                                                         None, distance=fph.combined_distance,
                                                         maxiter=200, virtual_atoms="selected")
        #lmimg = np.zeros_like(img)
        #for l in self.landmarks:
        #    lmimg[l[2],l[1]]=1
        #import matplotlib.pyplot as plt
        #fig, ax  = plt.subplots(2,3)
        #ax[0,0].imshow(self.ref_image, interpolation="none")
        #ax[0,0].set_title("Reference")
        #ax[1,0].imshow(lmimg, interpolation="none")
        #ax[1,0].set_title("Landmarks:")
        #ax[0,1].imshow(img1, interpolation="none")
        #ax[0,1].set_title("IntermediateA {}".format(scoreA))
        #ax[1,1].imshow(img2, interpolation="none")
        #ax[1,1].set_title("IntermediateB {}".format(scoreB))
        #ax[0,2].imshow(img, interpolation="none")
        #ax[0,2].set_title("Final {}".format(score))
        #ax[1,2].imshow(orig_img, interpolation="none")
        #ax[1,2].set_title("Rot/ offset unknown")
        #plt.show()
        self._last_measure = score
        return score*self.prefactor

    @profile
    def _find_offset(self, cg, projection_direction, mirror = False):
        if mirror: projection_direction = -projection_direction
        steplength = self.scale/self.ref_image.shape[0]
        cg.project_from = ftuv.normalize(projection_direction)
        ### Step 2: Find out offset and rotation.
        proj = fpp.Projection2D(cg, project_virtual_residues = [ x[0] for x in self.landmarks], project_virtual_atoms = "selected")
        target = []
        current = []
        for l in self.landmarks:
            target.append(np.array([l[2], l[1]])*steplength)
            current.append(proj.get_vres_by_position(l[0]))

        # The rotation (from optimal superposition)
        target = np.array(target)
        current = np.array(current)
        rotationMatrix = ftms.optimal_superposition(current, target)
        if mirror:
            rotationMatrix[0,1] = -rotationMatrix[0,1]
            rotationMatrix[1,0] = -rotationMatrix[1,0]
        c_rot = np.dot(current, rotationMatrix)
        bs = fph.get_box(proj, self.scale)
        offset_centroid = target - c_rot + np.array((bs[0],bs[2]))
        offset_centroid = ftuv.get_vector_centroid(offset_centroid)
        #The rotation angle in rad"""
        angle = math.atan2(rotationMatrix[1,0], rotationMatrix[0,0])

        #Calculate the bounding square using the offset.
        bs = fph.get_box(proj, self.scale, -offset_centroid)

        return proj, angle, -offset_centroid, bs
    @profile
    def _generate_equations(self, cg):
        penalty = 0
        #Preprocess: Calculate the projection angles for the shorthening of
        # the 3 pairwise distances between landmarks.
        angles = []
        vectors3d = []
        for i, (l0, l1) in enumerate(it.combinations(self.landmarks, 2)):
            vec = cg.get_virtual_residue(l1[0], True) - cg.get_virtual_residue(l0[0], True)
            vectors3d.append(vec)
            distance3d = ftuv.magnitude(vec)
            distance2d = ftuv.vec_distance(np.array([l0[1], l0[2]]), np.array([l1[1], l1[2]]))
            #print ("distance2d = ",distance2d ,"*", self.scale,"/", self.ref_image.shape[0])
            distance2d = distance2d * self.scale/self.ref_image.shape[0] #- (0.5*self.scale/self.ref_image.shape[0])
            try:
                theta = math.acos(distance2d/distance3d)
            except ValueError:
                if distance2d>distance3d:
                    #Projected distance > real distance
                    theta = 0
                    penalty += distance2d-distance3d
                else:
                    raise
            phi = math.pi / 2 - theta # The angle between the proj.-plane normal and the 3D vector
            #print ("distance3d {}, distance 2d {}, phi {}".format(distance3d, distance2d, math.degrees(phi)))
            angles.append(math.cos(phi))
        return vectors3d, angles, penalty

class DistanceExponentialEnergy(EnergyFunction):
    _shortname = "CLA"
    _DEFAULT_CLAMP_DISTANCE = 15.0
    HELPTEXT = ("Clamp elements (not nucleotides) together \n"
                "(at ADJ={} Angstrom) with an exponential energy\n"
                "The prefactor is used as scale (default 1).\n"
                "Requires the elements which will be\n"
                " clamped together.").format(_DEFAULT_CLAMP_DISTANCE)

    @classmethod
    def from_cg(cls, prefactor, adjustment, elem1, elem2, cg, **kwargs):
        """
        :param elem1: A coarse grained element name.
        :param elem2: A coarse grained element name.
        """
        return cls(elem1, elem2, distance = adjustment, scale = prefactor )

    def __init__(self, from_elem, to_elem, distance=None, scale=None):
        '''
        Create an exponential distribution for the distance between two elements.

        Here the prefactor gives the steepness of the exponential curve,
        while the adjustment gives the maximal distance that does not incur any penalty.
        '''
        if scale is None:
            scale = 1.
        if distance is None:
            distance = self._DEFAULT_CLAMP_DISTANCE
        super(DistanceExponentialEnergy, self).__init__(prefactor = scale, adjustment = distance)
        self.from_elem = from_elem
        self.to_elem = to_elem
        self.expon = scipy.stats.expon(loc=self.adjustment, scale=self.prefactor)

    def _update_pf(self):
        super(DistanceExponentialEnergy, self)._update_pf()
        self.expon = scipy.stats.expon(loc=self.adjustment, scale=self.prefactor)

    def _update_adj(self):
        super(DistanceExponentialEnergy, self)._update_adj()
        self.expon = scipy.stats.expon(loc=self.adjustment, scale=self.prefactor)

    def get_distance(self, cg):
        from_elem = self.from_elem
        to_elem = self.to_elem
        try:
            closest_points = ftuv.line_segment_distance(cg.coords[from_elem][0],
                                                        cg.coords[from_elem][1],
                                                        cg.coords[to_elem][0],
                                                        cg.coords[to_elem][1])
        except KeyError as e:
            failed_elem=str(e).strip("'")
            if failed_elem==from_elem or failed_elem==to_elem:
                raise LookupError("The following coarse-grained element is not "
                                  "part of the structure and thus cannot be "
                                  "used in the CLA energy: {}".format(failed_elem))
            raise

        closest_distance = ftuv.vec_distance(closest_points[1], closest_points[0])
        return closest_distance
    @property
    def shortname(self):
        if self.prefactor==1:
            name = "CLA"
        else:
            name = "{}CLA".format(self.prefactor)
        if self.adjustment != self._DEFAULT_CLAMP_DISTANCE:
            name = "{}{}".format(name, self.adjustment)
        return "{}({},{})".format(name,self.from_elem, self.to_elem)

    def eval_energy(self, cg, background=True, nodes=None, **kwargs):
        "This energy is always >0"
        closest_distance = self.get_distance(cg)

        if closest_distance < self.adjustment:
            return 0

        energy = -np.log(self.expon.pdf(closest_distance)) * 10.

        return energy



class StemVirtualResClashEnergy(EnergyFunction):
    '''
    Determine if the virtual residues clash.
    '''
    _shortname = "CLASH"
    _CLASH_DEFAULT_PREFACTOR = 50000.
    _CLASH_DEFAULT_ATOM_DIAMETER = 1.8
    IS_CONSTRAINT_ONLY = True
    can_constrain = "sm"
    HELPTEXT = "Clash constraint energy"


    def __init__(self, clash_penalty = None, atom_diameter = None):
        """
        :param clash_penalty: The energy attributed to each pair of clashing atoms
        :param atom_radius: The distance between two atoms which counts as a clash
        """
        if clash_penalty is None:
            clash_penalty = self._CLASH_DEFAULT_PREFACTOR
        if atom_diameter is None:
            atom_diameter = self._CLASH_DEFAULT_ATOM_DIAMETER
        # NOTE: The atom-diameter is implemented using the adjustment-variable!
        super(StemVirtualResClashEnergy, self).__init__(
                    prefactor = clash_penalty,
                    adjustment = atom_diameter    )
        self.bad_bulges = []
        self.bad_atoms = defaultdict(list)

    def _virtual_residue_atom_clashes_kd(self, cg):
        '''
        Check if any of the virtual residue atoms clash.
        '''
        virtual_atoms = []
        coords = []
        for key1 in self.vras.keys():
            for key2 in self.vras[key1].keys():
                virtual_atoms += [(self.vras[key1][key2], key1, key2)]
                coords += [self.vras[key1][key2]]

        if len(virtual_atoms) == 0:
            return 0

        #coords = np.vstack([p[0] for p in virtual_atoms])
        #coords = np.array([ line for line in np.array(virtual_atoms)[:,0]])
        coords = np.array(coords)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kdt2 = kd.KDTree(3)
            kdt2.set_coords(coords)
            kdt2.all_search(self.adjustment) #Distance in Angstrom. #1.8

        clashes = 0
        indeces = kdt2.all_get_indices()
        for (ia,ib) in indeces:
            if virtual_atoms[ia][1][0] == virtual_atoms[ib][1][0]:
                continue
            if virtual_atoms[ia][1] == virtual_atoms[ib][1]:
                continue

            key1 = virtual_atoms[ia][1]
            key2 = virtual_atoms[ib][1]

            resn1 = cg.stem_side_vres_to_resn(key1[0], key1[2], key1[1])
            resn2 = cg.stem_side_vres_to_resn(key2[0], key2[2], key2[1])

            #Adjacent residues cannot clash
            if abs(resn1 - resn2) == 1:
                continue
            clash_pair = tuple(sorted([key1[0], key2[0]]))
            if clash_pair not in self.bad_bulges:
                self.bad_bulges.append(clash_pair)
            self.bad_atoms[key1[0]].append(virtual_atoms[ia][0])
            self.bad_atoms[key2[0]].append(virtual_atoms[ib][0])
            clashes += 1

        return clashes

    def _virtual_residue_atom_clashes(self, cg, s1,i1,a1, s2, i2, a2):
        '''
        Check if any of the virtual residue atoms clash.

        This is a reference implementation without KD-Trees.
        Thus it is only used for testing!
        '''
        #(p1, v1, v1_l, v1_r) = ftug.virtual_res_3d_pos(bg, s1, i1)
        #(p2, v2, v2_l, v2_r) = ftug.virtual_res_3d_pos(bg, s2, i2)


        vra1 = self.vras[(s1,i1,a1)]
        vra2 = self.vras[(s2,i2,a2)]

        clashes = 0

        atoms1 = vra1
        atoms2 = vra2

        #for atoms1 in vra1:
            #for atoms2 in vra2:

        for a1 in atoms1.values():
            for a2 in atoms2.values():
                if ftuv.vec_distance(a1,a2) < 1.8:
                #if ftuv.magnitude(a1 - a2) < 1.8:
                    clashes += 1

        return clashes

    def eval_energy(self, cg, background=False, nodes = None, **kwargs):
        '''
        Count how many clashes of virtual residues there are.

        @param sm: The SpatialModel containing the list of stems.
        @param background: Use a background distribution to normalize this one.
                           This should always be false since clashes are independent
                           of any other energies.
        '''
        #: A dict of dicts. The first key is a triple (stem, a, b), e.g.: ('s27', 5, 1)
        #: Where a is the position within the strand and b is the stem (0 or 1)
        #: The key of the inner dict is the atom, e.g. "O3'"
        self.vras = dict()
        self.bases = dict()
        self.bad_bulges = []
        self.bad_atoms = defaultdict(list)
        self.last_clashes=[]
        mult = 8
        points = []
        energy = 0.

        if nodes is None:
            nodes = cg.defines.keys()

        log.debug("%s stems: %s", len([stem for stem in nodes if stem[0]=="s"]), nodes)
        if len([stem for stem in nodes if stem[0]=="s"])<2:
            # Special case, if only one stem is present.
            return 0.

        for d in nodes:
            if d[0] == 's':
                s = d
                s_len = cg.stem_length(s)
                #stem_inv = cg.stem_invs[s]
                log.debug("s %s, slen %s", s, s_len)
                for i in range(s_len):
                    (p, v, v_l, v_r) = cg.v3dposs[d][i]

                    points += [(p+ mult * v_l, d, i, 1)]
                    points += [(p+ mult * v_r, d, i, 0)]
        log.debug("points: %s, nodes %s, defines %s", points, nodes, cg.defines)
        coords = np.vstack([point[0] for point in points])
        clash_pairs = []
        #kk = ss.KDTree(np.array(l))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            kdt = kd.KDTree(3)
            kdt.set_coords(coords)
            kdt.all_search(10.)
        #print len(kdt.all_get_indices())
        #print len(kk.query_pairs(7.))
        indeces = kdt.all_get_indices()
        for (ia,ib) in indeces:
            (s1,i1,a1) = (points[ia][1], points[ia][2], points[ia][3])
            (s2,i2,a2) = (points[ib][1], points[ib][2], points[ib][3])
            clash_pairs += [((s1,i1,a1), (s2,i2,a2))]
            #print("NO NEW NODES: ", sorted(clash_pairs))

        #potential_clashes = 0
        for (s1, i1, a1), (s2,i2,a2) in clash_pairs:
            #if new_nodes != None:
            #    if s1 not in new_nodes and s2 not in new_nodes:
            #        continue

            if s1 == s2:
                continue

            if len(set.intersection(cg.edges[s1], cg.edges[s2])) > 0:
                # the stems are connected
                continue

            #potential_clashes += 1
            #fud.pv('s1,s2')

            if (s1,i1,a1) not in self.vras.keys():
                self.vras[(s1,i1,a1)] = ftug.virtual_residue_atoms(cg, s1, i1, a1)
            if (s2,i2,a2) not in self.vras.keys():
                self.vras[(s2,i2,a2)] = ftug.virtual_residue_atoms(cg, s2, i2, a2)

        energy += self.prefactor * self._virtual_residue_atom_clashes_kd(cg)
        return energy

class RoughJunctionClosureEnergy(EnergyFunction):
    _shortname = "JDIST"
    _JUNCTION_DEFAULT_PREFACTOR = 50000.
    IS_CONSTRAINT_ONLY = True
    can_constrain = "junction"
    HELPTEXT = "Junction constraint energy"
    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        if adjustment:
            warnings.warn("Adjustment {} ignored for JUNCT JunctionConstraintEnergy".format(repr(adjustment)))
        return cls(prefactor)
    def __init__(self, prefactor = None):
        if prefactor is None:
            prefactor = self._JUNCTION_DEFAULT_PREFACTOR
        super(RoughJunctionClosureEnergy, self).__init__(prefactor = prefactor)

    def eval_energy(self, cg, background=True, nodes=None, **kwargs):
        log.debug("Evaluating junction closure energy")
        if nodes == None:
            nodes = cg.defines.keys()

        self.bad_bulges = []
        all_bulges = set([d for d in nodes if (d[0] == 'm' and d in nodes)])
        energy = 0.

        for bulge in all_bulges:
            bl = cg.get_bulge_dimensions(bulge)[0]
            log.debug("Getting junction closure dist for %s", bulge)
            dist = ftug.junction_virtual_atom_distance(cg, bulge)
            #
            #cutoff_distance = (bl) * 5.9 + 13.4
            #cutoff_distance = (bl) * 5.908 + 11.309
            #cutoff_distance = (bl) * 6.4 + 6.4
            cutoff_distance = (bl) * 6.22 + 14.0 #Peter's cyclic coordinate descent
            # Note: DOI: 10.1021/jp810014s claims that a typical MeO-P bond is 1.66A long.

            if (dist > cutoff_distance):
                log.info("Junction closure: dist {} > cutoff {} for bulge {} with length {}".format(dist, cutoff_distance, bulge, bl))
                self.bad_bulges += cg.find_bulge_loop(bulge, 200) + [bulge]
                energy += (dist - cutoff_distance) * self.prefactor

        return energy

class MaxEnergyValue(EnergyFunction):
    _shortname = "MAX"
    can_constrain = "junction"
    IS_CONSTRAINT_ONLY = True
    HELPTEXT = ("This energy is non-negative, if its child energy\n"
                "is above a thresthold")
    @classmethod
    def from_cg(cls, pre, adj, argument, cg, **kwargs):
        other_energy, = EnergyFunction.from_string(argument, cg=cg, **kwargs)
        return cls(other_energy, adj)
    def __init__(self, other_energy, cutoff):
        super(MaxEnergyValue, self).__init__(adjustment = cutoff)
        self._other_energy = other_energy
        self.bad_bulges = []
    def eval_energy(self, cg, background=True, nodes=None, **kwargs):
        log.debug("MaxEnergyValue.eval_energy called. nodes=%s, "
                  "Calling other_energy %s", nodes, self._other_energy.shortname)
        e = self._other_energy.eval_energy(cg, background, nodes, **kwargs)
        if e>=self.adjustment:
            self.bad_bulges = self._other_energy.bad_bulges
            log.debug("MaxEnergyValue: Threshold exceeded: %s>=%s. Bad bulges: %s",e, self.adjustment, self.bad_bulges)
            return 10000.
        else:
            log.debug("MaxEnergyValue: Threshold not exceeded: {}<{}".format(e, self.adjustment))
            self.bad_bulges = []
            return 0.
    @property
    def shortname(self):
        sn = super(MaxEnergyValue, self).shortname
        return sn.replace(self._shortname, "{}({})".format(self._shortname,self._other_energy.shortname))

    def __getattr__(self, attr):
        log.debug("getattr of MAX energy called with %s", attr)
        return getattr(self._other_energy, attr)

class FragmentBasedJunctionClosureEnergy(EnergyFunction):
    _shortname = "FJC"
    can_constrain = "junction"
    HELPTEXT = ("A Fragment based energy")

    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, stat_source, **kwargs):
        energies = []
        mst = cg.get_mst()
        for ml in cg.mloop_iterator():
            if ml not in mst:
                log.debug("Creating %s energy for %s which is not in MST: %s", cls._shortname, ml, mst)
                energies.append(cls(ml, stat_source, prefactor=prefactor, adjustment=adjustment))
        return CombinedEnergy(energies)

    def __init__(self, element, stat_source, angular_weight=math.degrees(1)/4, prefactor = None, adjustment = None):
        self.element = element
        self.stat_source = stat_source
        # A deviation of 1 rad is equivalent to a deviation of how many angstrom
        self.angular_weight = angular_weight
        self.used_stat = None
        super(FragmentBasedJunctionClosureEnergy, self).__init__(prefactor = prefactor,
                                                                 adjustment = adjustment)

    def _stat_deviation(self, cg, virtual_stat):
        # Broken mls are ordered by connections
        s1, s2 = cg.connections(self.element)
        pdev, adev, tdev = ftug.get_broken_ml_deviation(cg, self.element,
                                                        s1,
                                                        virtual_stat)

        #pdev2, adev2, tdev2 = ftug.get_broken_ml_deviation(cg, self.element,
        #                                                s1,
        #                                                virtual_stat)
        #log.debug("PDEV: %s or %s, ADEV %s or %s, TDEV: %s or %s", pdev, pdev2, adev, adev2, tdev, tdev2)
        adev = math.degrees(adev)
        tdev = math.degrees(tdev)
        self.log.debug("Deviation: %s Angstrom, %s degrees (orientation), %s degrees (twist)", pdev, adev, tdev)
        adev = adev/4
        tdev = tdev/4
        self.log.debug("Weighted deviation: pos: %s, orient %s, twist: %s", pdev, adev, tdev)
        return max(pdev, adev, tdev)

    def eval_energy(self, cg, background=True, nodes=None,  sampled_stats=None, **kwargs):
        self.bad_bulges = []
        log.debug("{}.eval_energy called with nodes {}".format(self.shortname, nodes))
        if nodes is not None and self.element not in nodes:
            log.debug("Self.element %s not in nodes %s", self.element, nodes)
            return 0.
        best_deviation = float('inf')
        if sampled_stats is not None:
            log.debug("FJC using sampled stat!")
            assert self.element in sampled_stats
             # Assertion fails, if structure was built with JDIST energy but sampled
             # with this energy. Should never happen!
            assert sampled_stats[self.element] is not None
            self.used_stat = sampled_stats[self.element]
            best_deviation = self._stat_deviation(cg, sampled_stats[self.element])
        else:
            for stat in self.stat_source.iterate_stats_for(cg, self.element):
                curr_dev = self._stat_deviation(cg, stat)
                if curr_dev < best_deviation:
                    best_deviation = curr_dev
                    #log.debug("Setting used stat to %s, dev %s", stat, curr_dev)
                    self.used_stat = stat
        log.debug("FJC energy using fragment %s for element %s is %s", self.used_stat.pdb_name,
                                                                      self.element, best_deviation)
        self.bad_bulges = [self.element]
        return (best_deviation**self.adjustment)*self.prefactor

    @property
    def shortname(self):
        sn = super(FragmentBasedJunctionClosureEnergy, self).shortname
        return sn.replace(self._shortname, "{}({})".format(self._shortname,self.element))

class SampledFragmentJunctionClosureEnergy(FragmentBasedJunctionClosureEnergy):
    _shortname = "SFJ"
    can_constrain = "junction"
    HELPTEXT = ("An energy for the use with samplers like the\n"
                "WholeMLStatSearch and LocalMLMover that\n"
                "assign a stat to broken multiloop segments.\n"
                "Controlls, how well the assigned stat fits the\n"
                "true geometry of this segment.")

    def __init__(self, *args, **kwargs):
        super(SampledFragmentJunctionClosureEnergy, self).__init__( *args, **kwargs)
        del self.used_stat
    def eval_energy(self, cg, background=True, nodes=None, sampled_stats=None, **kwargs):
        self.log.debug("eval_energy called on SFJ(%s)", self.element)
        self.bad_bulges = []
        if nodes is not None and self.element not in nodes:
            return 0.
        try:
            sampled_pdb_name = cg.sampled[self.element][0]
        except KeyError:
            self.log.warning("Missing key %s in cg.sampled expected by SampledFragmentJunctionClosureEnergy. Returning energy of 0.", self.element)
            return 0.
        self.log.debug("Searching for sampled pdb_name=%r", sampled_pdb_name)
        if sampled_stats is None:
            for stat in self.stat_source.iterate_stats_for(cg, self.element):
                if stat.pdb_name == sampled_pdb_name:
                    break
            else:
                log.debug(list(map(str, self.stat_source.iterate_stats_for(cg, self.element))))
                raise ValueError("Sampled stat is inconsistent in SJF")
                self.log.warning("Sampled stat %s for %s not found in stat_source. Returning an energy of 0.", self.element, sampled_pdb_name)
                return 0.
        else:
            assert self.element in sampled_stats
            stat = sampled_stats[self.element]
        self.bad_bulges = [self.element]
        self.log.debug("Returning deviation for %s", stat.pdb_name)
        return (self._stat_deviation(cg, stat)**self.adjustment)*self.prefactor


def _iter_subgraphs(cg, use_subgraphs):
    """
    Generate a number of subgraphs. Used by generate_target_distribution of energies.

    :param cg: The CoarseGrainRNA
    :param use_subgraphs: A bool or int. See documentation of the energy

    :yields: A tuple (domain, nt_length)
    """


    if not use_subgraphs:
        return
    if len(cg.defines)<=5:
        return
    if isinstance(use_subgraphs, bool):
        target_range = list(range(3, len(cg.defines)-2))*100 # range starts at 3, because this is the
                                                               # smallest length containing 2 stems.
                                                               # For the same reason, we use len(defines)-2
                                                               # to exclude the complete RNA
    else:
        # use_subgraphs is an integer, giving the numbers of subgraphs per structure.
        target_range = []
        for i in range(use_subgraphs):
            target_range.append(random.randint(3, len(cg.defines.keys())-2))

    known_sgs = set([tuple(sorted(cg.defines.keys()))])
    for l in  target_range:
        subgraph =  cg.random_subgraph(l)
        assert len(subgraph) == len(set(subgraph))
        subgraph_t = tuple(sorted(subgraph))
        if subgraph_t not in known_sgs: #No duplicates. We sample without replacement
            known_sgs.add(subgraph_t)
            nt_length = sum(cg.element_length(elem) for elem in subgraph)
            yield subgraph, nt_length

class CheatingDistributionEnergy(CoarseGrainEnergy):
    _shortname = "CDE"
    HELPTEXT = ("Cheating Energy that samples RMSDs from \n"
                 "an exponential distribution with parameter\n"
                 "lambda = adjustment.")
    real_stats_fn = None
    sampled_stats_fn = "stats/cde_reference_dist_nr2.110.csv"
    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        return cls(cg, prefactor, adjustment)
    def __init__(self, ref_cg, prefactor = None, adjustment = None):
        super(CheatingDistributionEnergy, self).__init__(ref_cg.seq_length,
                                                         prefactor = prefactor,
                                                         adjustment = adjustment)
        self.real_residues = ftug.bg_virtual_residues(ref_cg)
    def _get_values_from_file(self, filename, rna_length):
        vals = []
        for line in load_local_data(filename):
            vals.append(float(line))
        return vals
    def _get_cg_measure(self, cg):
        new_residues = ftug.bg_virtual_residues(cg)
        return  ftms.rmsd(self.real_residues, new_residues)
    def _set_target_distribution(self):
        self.target_distribution = lambda x: self.adjustment*np.exp(-self.adjustment*x)

class RadiusOfGyrationEnergy(CoarseGrainEnergy):
    _shortname = "ROG"
    HELPTEXT = "Radius of gyration energy"
    real_stats_fn = op.expanduser('stats/rog_target_dist_1S72_0.csv')
    sampled_stats_fn = op.expanduser('stats/rog_reference_dist_1S72_0.csv')

    def __init__(self, rna_length, adjustment=None, prefactor=None):
        """
        :param rna_length: The length in nucleotides of the RNA
        """
        super(RadiusOfGyrationEnergy, self).__init__(rna_length, prefactor=prefactor, adjustment = adjustment)

    @classmethod
    def generate_target_distribution(cls, cgs, out_filename=None, use_subgraphs = False):
        """
        Generate the target distribution from the given cg-files and write it to a file

        .. warning::

            If out_filename is not given, this overwrites the file with the name given in
            `cls.real_stats_fn`.

        :param cgs: A list of CoarseGrainRNA objects
        :param out_filename: None or a filename relative to fess/
        :param use_subgraphs: Include the radius of subgraphs of the cg-files to get
                            more datapoints.
                            Either a bool or an integer.
                            If it is a bool, generate 100 subgraphs for each number of cg-elements possible.
                            If it is an integer: generate that many subgraphs with random length.
        """
        if out_filename is None:
            out_filename = cls.real_stats_fn
        else:
            out_filename = op.join("fess", out_filename)
        radii = []
        log.info("Generating target distribution for %s", cls.__name__)
        all_cg_names = []
        for cg in cgs:
            log.debug("Processing cg %s", cg.name)
            all_cg_names.append(cg.name)
            radii.append((cg.name, cg.seq_length, cg.radius_of_gyration("vres")))
            for subgraph, nt_length in _iter_subgraphs(cg, use_subgraphs):
                rog = ftmd.radius_of_gyration(cg.get_poss_for_domain([stem for stem in subgraph if stem[0]=="s"], mode = "fast"))
                radii.append((cg.name+".subgraph", nt_length, rog))
        log.info("Writing to file %s", out_filename)
        with open(out_filename, "w") as f:
            cls._print_file_header(f, all_cg_names)
            print("# use_subgraphs = {} ({})".format(use_subgraphs, type(use_subgraphs).__name__), file=f)
            for name, nt_len, rog in radii:
                print("{:s} {:d} {:.10f}".format(name, nt_len, rog), file=f)


    def _get_cg_measure(self, cg):
        return cg.radius_of_gyration("fast")

    def _get_values_from_file(self, filename, length):
        data = pd.read_csv(load_local_data(filename), delimiter=' ', comment="#", names=["pdb_id","nt_length","rog"])

        rdata = []

        distribution_upper_bound = 1.0
        distribution_lower_bound = 1.0
        target_len=500
        target_len=min(target_len,len(data[:]))
        while (len(rdata) < 500 and len(rdata)<len(data)):
            distribution_lower_bound -= INCR
            distribution_upper_bound += INCR

            mask_upper = data.iloc[:,1] < length * ( distribution_upper_bound )
            mask_lower = data.iloc[:,1] > ( distribution_lower_bound ) * length
            rdata = data.loc[ mask_upper & mask_lower ]

        rogs = rdata.iloc[:,2]
        rogs=np.array(rogs)

        return rogs

class NormalDistributedRogEnergy(RadiusOfGyrationEnergy):
    _shortname = "NDR"
    HELPTEXT = ("Normal Distributed ROG energy.\n"
               "Use a normal distribution for the target\n"
               "radius of gyration with 0.77*ADJ as mean \n"
               "and 0.23*ADJ stddev\n"
               "(0.77 is a rough estimate for the relation\n"
               " between perimeter and radius of gyration)\n")
    real_stats_fn = None
    sampled_stats_fn = op.expanduser('stats/rog_reference_dist_nr2.110.csv')

    def __init__(self, rna_length, adjustment, prefactor=None):
        """
        A Subclass of the Radius of Gyration energy with a normal distributed target distribution.

        The adjustment is treated as the estimated radius of the RNA. Thus the target distribution
        is a normal distribution with mean=0.77*ADJ and STDDEV=0.23*ADJ.

        Remember that the ROG for polymers is defined as:
        ROG=SQRT(1/N*Sum(r)) for N points with the mean in the origin.

        0.77 is roughly SQRT(3/5), which is the limes of the rog for m->inf many points
        in a 3D unit sphere with the nth point placed at radius (n/m)**1/3
        0.77-0.23 is roughly 1/SQRT(3), which is the limes of the rog for m->inf many points
        equally distributed along one or more diameters (in a star-like fashion)
        0.77+0.23 is 1, corresponding to all points on the surface of the sphere.

        If the radius is estimated from electron microscopy data,
        it is potentially smaller than the radius in 3D space if the shape of the RNA
        is not a perfect sphere.
        This effect is accounted for by allowing values greater than 1*ADJ with a
        non-neglectable probability

        :param rnalength: Used for initial reference distribution
        """
        super(NormalDistributedRogEnergy, self).__init__(rna_length, adjustment, prefactor)

    def _set_target_distribution(self):
        self.target_distribution = lambda x: np.array([scipy.stats.norm(loc=0.77*self.adjustment, scale=0.23*self.adjustment).pdf(x)])


class AMinorEnergy(CoarseGrainEnergy):
    _shortname = "AME"
    HELPTEXT = "A-Minor energy"
    LOOPS=["i", "h"]
    data_filename = op.expanduser("stats/AME_distributions.csv")
    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        """
        Get the A-minor energiy for the CoarseGrainedRNA

        :param pre: Energy prefactor
        :param adj: Adjustment

        :returns: An AMinorEnergy instance
        """
        return cls(len(list(cg.stem_iterator()), prefactor=prefactor, adjustment=adjustment))

    def __init__(self, num_stems, prefactor, adjustment, knowledge_weight=1000):
        """
        :param num_stems: Number of stems in the cg.
        :param knowledge_weight: The weight of the initial reference distribution,
                                 given as the number of sampling steps it should correspond to.
        """
        self.knowledge_weight=knowledge_weight

        # Index telling us, what accepted measures have already been added to the reference distr.
        self._accepted_measure_start_index=0

        # Note: self._accepted_measures (initialized in super)
        #       lists in this case tuples of dicts.
        super(AMinorEnergy, self).__init__(num_stems, prefactor, adjustment)

    def reset_distributions(num_stems):
        data = pd.read_csv(cls.data_filename)
        # sum of interacting and non-interacting loops in reference distribution
        self.reference_length={}
        # interacting loops
        self.reference_interactions={}
        # Target interaction probability
        self.target_fraction={}
        for loop in self.LOOPS:
            loop_data=data[data["typ"]==loop]
            max_stems=max(loop_data["stems"])
            stems=min(max_stems, num_stems)
            row=loop_data[loop_data["stems"]==stems]
            target, = row["target"].values
            background, = row["random"]
            self.target_fraction[loop]=target
            self.reference_interactions[loop]=int(knowledge_weight*background)
            self.reference_length[loop]+=knowledge_weight

    def eval_energy(self, cg, background=True, nodes=None, use_accepted_measure=False,
                    plot_debug=False):
        if plot_debug or nodes is not None:
            raise NotImplementedError("'plot_debug' and 'nodes' args are not implemented"
                                      " for AMinorEnergy")
        if use_accepted_measure:
            m = self.accepted_measures[-1]
        else:
            m = self._get_cg_measure(cg)

        self._last_measure=m

        energy=0
        # The straight forward implementation of a Coarse Grained Energy would be
        # to assign an energy to interactions and a different energy to non-interactions.
        # However, since 0 is arbitrary, we choose to set non-interactions to 0
        # and adjust the energy of interactions.
        # This means that the energy of structures without interactions is not adjusted by the
        # reference ratio method, only the energy of interactions is adjusted.
        loop_counts, interaction_counts = m
        for loop in LOOPS:
            num_interactions=interaction_counts[loop]
            target_perc = self.target_fraction[loop]*self.adjustment
            reference_perc = self.reference_interactions[loop]/self.reference_length[loop]
            if background:
                e_i = -np.log( target_perc) + np.log(reference_perc)
                e_noi = -np.log( 1-target_perc) + np.log(1-reference_perc)
            else:
                e_i=-np.log(target_perc)
                e_noi=-np.log(1-target_perc)
            energy_contrib = e_i-e_noi
            log.debug("Energy contribution for loop type %s = %s, "
                      "with %s interactions", loop, energy_contrib, num_interactions)
            energy+=energy_contrib*num_interactions
        return self.prefactor*energy

    def _set_target_distribution(self):
        """
        Not needed, since the adjustment is multiplied to the
        target value in every eval_energy call
        """
        pass

    def resample_background_kde(self):
        for loop in self.LOOPS:
            for m in self.accepted_measures[self._accepted_measure_start_index:]:
                loop_counts, interaction_counts = m
                self.reference_interactions[loop]+=interaction_counts[loop]
                self.reference_length[loop]+=loop_counts[loop]
        self._accepted_measure_start_index=len(self.accepted_measures)

    def dump_measures(self, base_directory, iteration=None):
        output_file = op.join(base_directory, self.name+"_"+str(hex(id(self)))+".measures")
        lines=[]
        for loop in self.LOOPS:
            loop_counts=0
            interaction_counts=0
            for m in self.accepted_measures:
                loop_counts+=m[0][loop]
                interaction_counts+=m[1][loop]
            lines.append("{:s} {:d} {:d}\n".format(loop, loop_count, interaction_count))

        with open(output_file, 'w') as f:
            print("".join(lines), file=f)
        if iteration is not None:
            with open(output_file + ".%d" % (iteration), 'w') as f:
                print("".join(lines), file=f)

    @property
    def last_accepted_measure(self):
        m=self.accepted_measures[-1]
        return sum(m[1].values())/sum(m[0].values())

    def _get_cg_measure(self, cg):
        interactions = ftca.all_interactions(cg)
        interactions = set(pair[0] for pair in interactions)
        loop_counts=Counter()
        interaction_counts=Counter()
        for loop in self.LOOPS:
            for d in cg.defines:
                if d[0]!=loop:
                    continue
                if d not in cg.incomplete_elements and d not in cg.interacting_elements:
                    if d in interactions:
                        interaction_counts[loop]+=1
                    loop_counts[loop]+=1
        return loop_counts, interaction_counts

class DoNotContribute(Exception):
    pass


def _minimal_h_h_distance(cg, elem1, elem2_iterator):
    """
    Used by ShortestLoopDistancePerLoop-Energy.

    :param cg: The CoarseGrain RNA
    :param elem1: A STRING. A name of a hairpin loop. e.g. "h1"
    :param elem2_iterator: A ITERATOR/ LIST. Element names to compare h1 with.
    """
    min_dist = float("inf")
    for elem2 in elem2_iterator:
        if elem2==elem1: continue
        (i1,i2) = ftuv.line_segment_distance(cg.coords[elem1][0],
                                            cg.coords[elem1][1],
                                            cg.coords[elem2][0],
                                            cg.coords[elem2][1])
        dist = ftuv.vec_distance(i1, i2)
        if dist < min_dist:
            min_dist = dist
    return min_dist

class ShortestLoopDistancePerLoop(CoarseGrainEnergy):
    _shortname = "SLD"
    HELPTEXT = "shortest loop distance per loop"
    real_stats_fn = 'stats/sld_target_dist_1S72_0.csv'
    sampled_stats_fn = 'stats/sld_reference_dist_1S72_0.csv'

    @classmethod
    def from_cg(cls, prefactor, adjustment, cg, **kwargs):
        """
        Get the shortest loopdistance per loop energy for each hloop.

        :param cg: The coarse grained RNA
        :returns: A CombinedEnergy
        """
        energies=[]
        for hloop in cg.hloop_iterator():
            energies+= [cls(rna_length = cg.seq_length, loop_name = hloop,
                            prefactor = prefactor, adjustment = adjustment)]
        return CombinedEnergy(energies)

    @classmethod
    def generate_target_distribution(cls, cgs, out_filename=None, use_subgraphs = False):
        """
        Generate the target distribution from the given cg-files and write it to a file

        .. warning::

            If out_filename is not given, this overwrites the file with the name given in
            `cls.real_stats_fn`.

        :param cgs: A list of cg-objects.
        :param out_filename: None or a filename relative to fess/
        :param use_subgraphs: Include the radius of subgraphs of the cg-files to get
                            more datapoints.
                            Either a bool or an integer.
                            If it is a bool, generate 100 subgraphs for each number
                            of cg-elements possible.
                            If it is an integer: generate that many subgraphs with random length.

        """
        if out_filename is None:
            out_filename = cls.real_stats_fn
        else:
            out_filename = op.join("fess", out_filename)


        distances = []
        log.info("Generating target distribution for %s", cls.__name__)

        loop_loop_distances = []
        all_cg_names = []
        for cg in cgs:
            cg = ftmc.CoarseGrainRNA.from_bg_file(fname)
            pdbid = cg.name
            all_cg_names.append(pdbid)
            log.info("Processing cg %s", pdbid)
            for h1 in cg.hloop_iterator():
                min_dist = _minimal_h_h_distance(cg, h1, cg.hloop_iterator())
                if min_dist<float("inf"):
                    loop_loop_distances.append((pdbid, cg.seq_length, min_dist))
            pdbid = cg.name+".subgraph"
            for subgraph, nt_length in _iter_subgraphs(cg, use_subgraphs):
                for h1 in subgraph:
                    if h1[0]!="h":
                        continue
                    min_dist = _minimal_h_h_distance(cg, h1, (h for h in subgraph if h[0]=="h"))
                    if min_dist<float("inf"):
                        loop_loop_distances.append((pdbid, nt_length, min_dist))

        log.info("Writing to file %s", out_filename)
        with open(out_filename, "w") as f:
            cls._print_file_header(f, all_cg_names)
            print("# use_subgraphs = {} ({})".format(use_subgraphs, type(use_subgraphs).__name__), file=f)
            for pdbid, nt_len, distance in loop_loop_distances:
                print("{:s} {:d} {:.10f}".format(pdbid, nt_len, distance), file=f)


    def __init__(self, rna_length, loop_name, prefactor=None, adjustment = None):

        #: Add equally distributed points to the target and reference distribution estimation (linspacepoints  lsp)
        #: Weight of the uniformal distribution that will be averaged to the KDE
        self._lsp_weight = 0.1
        #: Start of the range for the uniformal distribution
        self._lsp_min = 3
        #: End of the range for the uniformal distribution
        self._lsp_max = 300

        super(ShortestLoopDistancePerLoop, self).__init__(rna_length, prefactor, adjustment)
        self.loop_name = loop_name

    @property
    def shortname(self):
        sn = super(ShortestLoopDistancePerLoop, self).shortname
        return sn.replace(self._shortname, "{}({})".format(self._shortname,self.loop_name))

    def _get_values_from_file(self, filename, length):
        data = pd.read_csv(load_local_data(filename), delimiter=' ', comment="#", names=["pdb_id","nt_length","dist"])
        data = self._values_within_nt_range(data, length, "dist", "nt_length" )
        return data

    def _get_distribution_from_values(self, values):
        f = super(ShortestLoopDistancePerLoop, self)._get_distribution_from_values(values)
        log.debug("Getting distributions")
        def kde_with_uniform(measure):
            x1 = f(measure)
            assert self._lsp_max>self._lsp_min
            if np.all(measure<self._lsp_max) and np.all(measure>self._lsp_min):
                x2=1/(self._lsp_max-self._lsp_min)
            else:
                x2=0
            log.debug("Mixed distr: x1 = %s, x2 = %s", x1, x2)
            return (1-self._lsp_weight)*x1+self._lsp_weight*x2
        return kde_with_uniform

    def _get_cg_measure(self, cg):
        min_dist = _minimal_h_h_distance(cg, self.loop_name, cg.hloop_iterator())
        return min_dist
    def eval_energy(self, cg, background=True, nodes=None, **kwargs):
        '''
        We want to return an energy of 0. if there's less than two hairpin
        loops.
        '''
        if len(list(cg.hloop_iterator())) < 2:
            return 0.
        else:
            try:
                energy= super(ShortestLoopDistancePerLoop, self).eval_energy(cg,
                                                                         background,
                                                                         nodes, **kwargs)
            except DoNotContribute:
                energy=0
            return energy

class CombinedFunction(object):
    def __init__(self, funcs):
        self._funcs = funcs
    def __call__(self, *args, **kwargs):
        results = []
        for fun in self._funcs:
            results.append(fun(*args, **kwargs))
        log.debug("Combined Function called. Results are {}".format(results))
        if not results or results[0] is None:
            return None
        return results

class CombinedEnergy(object):
    def __init__(self, energies=None, normalize=False):
        """
        :param normalize: Divide the resulting energy by the numbers of contributions
        """
        if energies:
            log.info("Setting up combined energy with contributions %s", energies)
        else:
            log.debug("Setting up combined energy with contributions %s", energies)

        if energies is not None:
            super(CombinedEnergy, self).__setattr__("energies", energies)
        else:
            super(CombinedEnergy, self).__setattr__("energies", [])
        super(CombinedEnergy, self).__setattr__("constituing_energies", [])
        super(CombinedEnergy, self).__setattr__("normalize", normalize)

    def __setattr__(self, name, val):
        if name not in self.__dict__:
            for e in self.energies:
                setattr(e, name, val)
        else:
            self.__dict__[name]=val

    def __getattr__(self, name):
        #If no energies are present, do nothing (DON'T raise an error)
        if not self.energies:
            return CombinedFunction([])
        log.debug("getattr delegating call to {}".format(name))
        attrs = []
        for e in self.energies:
            try:
                attrs.append(getattr(e, name))
            except AttributeError as e:
                if hasattr(CoarseGrainEnergy, name):
                    # If the function only exists for CoarseGrainEnergies,
                    # but not for normal Energy functions,
                    # call it only on CoarseGrainEenrgies.
                    pass
                else:
                    # Else this is an error.
                    raise AttributeError("CombinedEnergy has no attribute '{}', because {}".format(name, e))
        if len(attrs)==1:
            return attrs[0]
        try:
            return sum(attrs)
        except:
            pass
        try:
            return join(attrs)
        except:
            pass
        return CombinedFunction(attrs)

    def uses_background(self):
        for e in self.energies:
            if isinstance(e, CoarseGrainEnergy):
                return True
        return False

    def iterate_energies(self):
        """
        Iterate over all member enegies
        in a way that flattens nested CombinedEnergies.
        """
        for e in self.energies:
            if hasattr(e, "iterate_energies"):
                for e2 in e.iterate_energies():
                    yield e2
            else:
                yield e

    def remove_energies_if(self, function):
        new_energies = []
        for e in self.energies:
            if not function(e):
                new_energies.append(e)
            else:
                log.debug("Removing energy %s", e.shortname)
        self.energies = new_energies
    @property
    def can_constrain(self):
        can_constrain = []
        for e in self.iterate_energies():
            can_constrain.append(e.can_constrain)
        if all(c == can_constrain[0] for c in can_constrain):
            return can_constrain[0]
        else:
            return "inconsistent"

    @property
    def shortname(self):
        name=[]
        for e in self.energies:
            name.append(e.shortname)
        sn=",".join(name)

        return sn

    @property
    def bad_bulges(self):
        bad_bulges = []
        for e in self.energies:
            if hasattr(e, "bad_bulges"):
                log.debug("%s has bad_bulges: %s", e, e.bad_bulges)
                bad_bulges+=e.bad_bulges
            else:
                log.debug("%s doesn't have bad bulges")
        log.debug("Returning bad bulges %s", bad_bulges)
        return bad_bulges
    def eval_energy(self, cg, background=True, nodes=None, verbose=False,
                    use_accepted_measure=False, plot_debug=False, **kwargs):
        total_energy = 0.
        self.constituing_energies=[]
        num_contribs=0

        for energy in self.energies:
            contrib = energy.eval_energy(cg, background=background, nodes=nodes,
                                         use_accepted_measure=use_accepted_measure,
                                         plot_debug = plot_debug, **kwargs)

            if not np.isscalar(contrib):
                raise TypeError
                contrib, = contrib
            self.constituing_energies.append((energy.shortname, contrib))
            total_energy += contrib
            num_contribs +=1

            if verbose:
                print (energy.name, energy.shortname, contrib)
                if energy.bad_bulges:
                    print("bad_bulges:", energy.bad_bulges)
            log.debug("Combined energy instance at {}: {} ({}) contributing {}".format(id(self), energy.__class__.__name__, energy.shortname, contrib))


        if num_contribs>0:
            if self.normalize:
                total_energy=total_energy/num_contribs
        else:
            assert self.energies == []

        if verbose:
            print ("--------------------------")
            print ("total_energy:", total_energy)
        log.debug("{} [{}] at {}: total energy is {}".format(str(self), self.shortname, id(self), total_energy))
        return total_energy

    def __str__(self):
        out_str = 'CombinedEnergy('
        for en in self.energies:
            out_str += en.__class__.__name__ + ","
        return out_str[:-1]+")"

    def __len__(self):
        return len(self.energies)

    def hasinstance(self, cls):
        """
        Returns True, if any of the member energies is an instance of the given class
        """
        for e in self.energies:
            if hasattr(e, "hasinstance"):
                if e.hasinstance(cls): return True
            elif isinstance(e, cls):
                return True
        return False

    def __bool__(self):
        if not self.energies:
            return False
        else:
            return any(e for e in self.energies)

    __nonzero__=__bool__
####################################################################################################
## Convenience functions for creating energies
####################################################################################################


def update_parser(parser):
    helptext = "\n".join(
                    ["Specify a ','-separated list of energy contributions.\n"
                   "Each contribution has the format: [PRE]TYP[ADJ].\n"
                   "PRE: optional energy prefactor\n"
                   "ADJ: optional adjustment of target distribution\n"
                   "     (float), default=1.0\n"
                   "For simulated annealing, ADJ and PRE can be changed \n"
                   "     during the simulation. To achieve this, give \n"
                   "     underscore-seperated values START_STEP_FREQUENCY \n"
                   "     as PRE and/or ADJ. The value will start with \n"
                   "     START and be incremented by STEP every \n"
                   "     FREQUENCY sampling steps."
                   "     E.g. 1.0_0.1_100 means start at 1.0 and \n"
                   "     increment this value by 0.1 after every\n"
                   "     100 sampling steps.\n"
                   "TYP: One of the following:"])
    EnergyFunction.add_to_parser(parser, '--energy', default="ROG,AME,SLD", help_intro=helptext)


def from_args(args, cg, stat_source, replica=None):
    energy_string = replica_substring(args.energy, replica)
    energies = EnergyFunction.from_string(energy_string,
                                          cg=cg,
                                          stat_source=stat_source)
    return CombinedEnergy(energies)

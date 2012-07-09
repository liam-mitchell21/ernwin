#!/usr/bin/python

from corgy.utilities.data_structures import DefaultDict
from corgy.visual.pymol import PymolPrinter
from corgy.builder.stats import AngleStat, AngleStatsDict
from corgy.builder.stats import StemStat, StemStatsDict
from corgy.graph.graph_pdb import stem2_pos_from_stem1
from corgy.graph.graph_pdb import stem2_orient_from_stem1
from corgy.graph.graph_pdb import twist2_orient_from_stem1
from corgy.graph.graph_pdb import twist2_from_twist1
from corgy.utilities.vector import get_double_alignment_matrix

from numpy import array
from random import choice, uniform
from sys import stderr
from math import pi


class StemModel:
    '''
    A way of encapsulating the coarse grain 3D stem.
    '''

    def __init__(self, mids=None, twists=None):
        if mids == None:
            self.mids = (array([0., 0., 0.]), array([0., 0., 1.0]))
        else:
            self.mids = mids
        if twists == None:
            self.twists = (array([0., 1., 0.]), array([1., 0., 0.0]))
        else:
            self.twists = twists

    def __str__(self):
        return str(self.mids) + '\n' + str(self.twists)

    def reverse(self):
        '''
        Reverse this stem's orientation so that the order of the mids
        is backwards. I.e. mids[1] = mids[0]...
        '''
        return StemModel((self.mids[1], self.mids[0]), (self.twists[1], self.twists[0]))

    def vec(self, (from_side, to_side) = (0, 1)):
        return self.mids[to_side] - self.mids[from_side]

class BulgeModel:
    '''
    A way of encapsulating a coarse grain 3D loop.
    '''

    def __init__(self, mids=None):
        if mids == None:
            self.mids = (array([0., 0., 0.]), array([0., 0., 1.0]))
        else:
            self.mids = mids

    def __str__(self):
        return str(self.mids)
            

class SpatialModel:
    '''
    A way of building RNA structures given angle statistics as well
    as length statistics.
    '''

    def __init__(self, bg, angle_stats, stem_stats, loop_stats, angle_defs = None, stem_defs = None, loop_defs = None):
        '''
        Initialize the structure.

        @param bg: The BulgeGraph containing information about the coarse grained
                   elements and how they are connected.
        @param angle_stats: The statistics about the inter-helical angles.
        @param angle_defs: Pre-determined statistics for each bulge
        '''

        self.angle_stats = angle_stats
        self.stem_stats = stem_stats
        self.loop_stats = loop_stats

        self.bg = bg
        self.pymol_printer = PymolPrinter()

        if angle_defs == None:
            self.sample_angles()
        else:
            self.angle_defs = angle_defs

        if stem_defs == None:
            self.sample_stems()
        else:
            self.stem_defs = stem_defs

        if loop_defs == None:
            self.sample_loops()
        else:
            self.loop_defs = loop_defs

        pass

    def sample_angles(self):
        '''
        Sample statistics for each bulge region. In this case they'll be random.

        @return: A dictionary where the key is the name of a bulge and the value is a 
            statistic for the angles of that bulge.
        '''
        angle_defs = dict()
        angle_defs['start'] = AngleStat()

        for d in self.bg.defines.keys():
            if d[0] != 's' and len(self.bg.edges[d]) == 2:
                size = self.bg.get_bulge_dimensions(d)
                stats = choice(self.angle_stats[size[0]][size[1]])

                angle_defs[d] = stats

        self.angle_defs = angle_defs

    def sample_stems(self):
        '''
        Sample statistics for each stem region.

        @return: A dictionary containing statistics about the stems in the structure.
        '''
        stem_defs = dict()

        for d in self.bg.defines.keys():
            if d[0] == 's':
                define = self.bg.defines[d]
                length = abs(define[1] - define[0])

                # retrieve a random entry from the StemStatsDict collection
                ss = choice(self.stem_stats[length])
                stem_defs[d] = ss

        self.stem_defs = stem_defs

    def sample_loops(self):
        '''
        Sample statistics for each loop region.

        @return: A dictionary containing statistics about the loops in the structure.
        '''
        loop_defs = dict()

        for d in self.bg.defines.keys():
            if d[0] != 's' and len(self.bg.edges[d]) == 1:
                define = self.bg.defines[d]
                length = abs(define[1] - define[0])

                # retrieve a random entry from the StemStatsDict collection
                ls = choice(self.loop_stats[length])
                loop_defs[d] = ls

        self.loop_defs = loop_defs

    def add_loop(self, name, prev_stem_node, params=None):
        '''
        Connect a loop to the previous stem.
        '''
        prev_stem = self.stems[prev_stem_node]
        (s1b, s1e) = self.bg.get_sides(prev_stem_node, name)

        if params == None:
            length = self.loop_defs[name].phys_length
            u = uniform(0, pi)
            v = uniform(-pi/2, pi/2)

            params = (length, u, v)

        start_mid = prev_stem.mids[s1b]
        (r, u, v) = params

        direction = stem2_pos_from_stem1(prev_stem.vec((s1e, s1b)), prev_stem.twists[s1b], (r, u, v))
        end_mid = start_mid + direction
        self.bulges[name] = BulgeModel((start_mid, end_mid))


    def find_start_node(self):
        '''
        Find a node from which to begin building. This should ideally be a loop
        region as from there we can just randomly orient the first stem.
        '''
        for define in self.bg.defines.keys():
            if define[0] != 's' and self.bg.weights[define] == 1 and len(self.bg.edges[define]) == 1:
                for edge in self.bg.edges[define]:
                    self.to_visit += [(edge, 'start', StemModel())] 

                break


    def get_transform(self, edge):
        '''
        Get the location of one end of a stem.

        Used in aligning a group of models around a single edge.

        @param edge: The name of the edge.
        '''
        assert(edge[0] == 's')
        
        return self.stems[edge].mids[0]

    def get_rotation(self, edge):
        '''
        Get a rotation matrix that will align a point in the direction of a particular
        edge.

        Used in aligning a group of models around a single edge.
        
        @param edge: The name of the target edge.
        '''
        assert(edge[0] == 's')

        target = [array([1., 0., 0.]), array([0., 1., 0.])]


        vec1 = self.stems[edge].vec()
        twist1 = self.stems[edge].twists[1]

        mat = get_double_alignment_matrix(target, [vec1, twist1])

        return mat

    def get_random_stem_stats(self, name):
        '''
        Return a random set of parameters with which to create a stem.
        '''

        return self.stem_defs[name]

    def get_random_bulge_stats(self, name):
        '''
        Return a random set of parameters with which to create a bulge.
        '''

        return self.angle_defs[name]

    def add_stem(self, stem_params, prev_stem, bulge_params, (s1b, s1e)):
        '''
        Add a stem after a bulge. 

        The bulge parameters will determine where to place the stem in relation
        to the one before it (prev_stem). This one's length and twist are
        defined by the parameters stem_params.

        @param stem_params: The parameters describing the length and twist of the stem.
        @param prev_stem: The location of the previous stem
        @param bulge_params: The parameters of the bulge.
        @param side: The side of this stem that is away from the bulge
        '''
        start_location = stem2_pos_from_stem1(prev_stem.vec((s1b, s1e)), prev_stem.twists[s1e], bulge_params.position_params())
        stem_orientation = stem2_orient_from_stem1(prev_stem.vec((s1b, s1e)), prev_stem.twists[s1e], [stem_params.phys_length] + list(bulge_params.orientation_params()))
        twist1 = twist2_orient_from_stem1(prev_stem.vec((s1b, s1e)), prev_stem.twists[s1e], bulge_params.twist_params())
    
        stem = StemModel()

        mid1 = prev_stem.mids[s1e] + start_location
        mid2 = mid1 + stem_orientation

        stem.mids = (mid1, mid2)

        twist2 = twist2_from_twist1(stem_orientation, twist1, stem_params.twist_angle)

        stem.twists = (twist1, twist2)

        return stem

    def fill_in_bulges_and_loops(self):
        for d in self.bg.defines.keys():
            if d[0] != 's':
                if len(self.bg.edges[d]) == 1:
                    self.add_loop(d, list(self.bg.edges[d])[0])
                    # add loop
                    pass
                else:
                    connections = list(self.bg.edges[d])

                    # Should be a bulge connecting two stems
                    assert(len(connections) == 2)
                    for conn in connections:
                        assert(conn[0] == 's')

                    (s1b, s1e) = self.bg.get_sides(connections[0], d)
                    (s2b, s2e) = self.bg.get_sides(connections[1], d)

                    s1mid = self.stems[connections[0]].mids[s1b]
                    s2mid = self.stems[connections[1]].mids[s2b]

                    self.bulges[d] = BulgeModel((s1mid, s2mid))

    def elements_to_coords(self):
        '''
        Add all of the stem and bulge coordinates to the BulgeGraph data structure.
        '''

        for stem in self.stems.keys():
            sm = self.stems[stem]

            self.bg.coords[stem] = (sm.mids[0], sm.mids[1])
            self.bg.twists[stem] = (sm.twists[0], sm.twists[1])

        for bulge in self.bulges.keys():
            bm = self.bulges[bulge]

            self.bg.coords[bulge] = (bm.mids[0], bm.mids[1])

    def traverse_and_build(self):
        '''
        Build a 3D structure from the graph in self.bg.

        This is done by doing a breadth-first search through the graph
        and adding stems. 

        Once all of the stems have been added, the bulges and loops
        are added.
        '''

        self.visited = set()
        self.to_visit = []
        self.stems = dict()
        self.bulges = dict()
        self.sampled_bulges = []

        # the start node should be a loop region
        self.find_start_node()

        counter = 0
        self.bg.coords = dict()

        while len(self.to_visit) > 0:
            (curr_node, prev_node, prev_stem) = self.to_visit.pop(0)

            while curr_node in self.visited:
                if len(self.to_visit) > 0:
                    (curr_node, prev_node, prev_stem) = self.to_visit.pop(0)
                else:
                    return
                    
            self.visited.add(curr_node)
            stem = prev_stem

            if curr_node[0] == 's':
                params = self.get_random_stem_stats(curr_node)
                if prev_node == 'start':
                    (s1b, s1e) = (1,0)
                else:
                    (s1b, s1e) = self.bg.get_sides(curr_node, prev_node)

                # get some parameters for the previous bulge
                prev_params = self.get_random_bulge_stats(prev_node)
                self.sampled_bulges += [prev_node]

                # the previous stem should always be in the direction(0, 1) 
                if prev_node == 'bg':
                    stem = self.add_stem(params, prev_stem, prev_params, (1, 0))
                else:
                    stem = self.add_stem(params, prev_stem, prev_params, (0, 1))

                # the following is done to maintain the invariant that mids[s1b] is
                # always in the direction of the bulge from which s1b was obtained
                # i.e. s1e -> s1b -> bulge -> s2b -> s2e
                if s1b == 1:
                    self.stems[curr_node] = stem.reverse()
                else:
                    self.stems[curr_node] = stem

                #self.stems[curr_node] = stem

            for edge in self.bg.edges[curr_node]:
                if edge not in self.visited:
                    self.to_visit.append((edge, curr_node, stem))

            counter += 1

        self.fill_in_bulges_and_loops()
        
        self.elements_to_coords()



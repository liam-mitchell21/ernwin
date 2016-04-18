#!/usr/bin/python
from __future__ import print_function

import collections as c
import sys, random, copy
import numpy as np
import math, os
import time

import scipy.stats as ss

#import matplotlib.pyplot as plt
from . import samplingStatisticsNew2 as sstats
import fess.builder.config as cbc
import fess.builder.energy as fbe
import forgi.threedee.model.comparison as ftme
import forgi.threedee.model.stats as cbs

import forgi.threedee.utilities.graph_pdb as ftug
import forgi.threedee.utilities.vector as ftuv
import forgi.utilities.debug as fud

import forgi.threedee.utilities.rmsd as cbr
import fess.builder.models as cbm

import numpy as np

class StatisticsPlotter:
    '''
    Plot a histogram of the rmsd as well as a plot of the energy vs. the rmsd.
    '''
    def __init__(self):
        import matplotlib.pyplot as plt
        import pylab as pl
        pl.ion()

        self.fig = plt.figure(figsize=(9, 9))

        self.ax_hist = self.fig.add_subplot(2, 1, 1)
        self.ax_plot = self.fig.add_subplot(2, 1, 2, sharex=self.ax_hist)

        self.energies = c.defaultdict(list)
        self.rmsds = c.defaultdict(list)


        self.energy_rmsds = []

        self.ax_plot.set_xlabel('rmsd')
        self.ax_hist.set_xlabel('rmsd')
        
        plt.ion()

    def create_contour_plot(self, m1, m2, ax, xlim, ylim, color):
        import matplotlib.pyplot as plt
        new_m1 = []
        new_m2 = []

        for i in range(len(m1)):
            if m1[i] > xlim[0] and m1[i] < xlim[1] and m2[i] > ylim[0] and m2[i] < ylim[1]:
                new_m1 += [m1[i]]
                new_m2 += [m2[i]]

        #positions = np.vstack([X.ravel(), Y.ravel()])
        X, Y = np.mgrid[xlim[0]:xlim[1]:complex(0,len(new_m1)), ylim[0]:ylim[1]:complex(0, len(new_m2))]
        #X,Y = np.meshgrid(new_m1, new_m2)
        positions = np.vstack([X.ravel(), Y.ravel()])
        values = np.vstack([m1, m2])
        try:
          kernel = ss.gaussian_kde(values)
        except: pass
        else:
            Z = np.reshape(kernel(positions).T, X.shape)
            if color == 'b':
                ax.contourf(X, Y, Z, cmap=plt.cm.Blues,alpha=0.5)
            if color == 'r':
                ax.contourf(X, Y, Z, cmap=plt.cm.Reds,alpha=0.5)
            if color == 'g':
                ax.contourf(X, Y, Z, cmap=plt.cm.Greens, alpha=0.5)
            if color == 'y':
                ax.contourf(X, Y, Z, cmap=plt.cm.YlOrBr, alpha=0.5)

    def add_data(self, energy, rmsd, color):
        self.energies[color] += [energy]
        self.rmsds[color] += [rmsd] 


        self.energy_rmsds += [(energy, rmsd, color)]

        all_energies = []
        all_rmsds = []

        for color in self.energies.keys():
            all_energies += list(self.energies[color])
            all_rmsds += list(self.rmsds[color])

        sorted_energy_rmsds = sorted(self.energy_rmsds)

        sorted_energies = sorted(all_energies)
        sorted_rmsds = sorted(all_rmsds)

        self.ax_hist.cla()

        if len(sorted_energies) % 2 == 0:
            self.ax_plot.cla()

            if len(sorted_energies) > 4:
                ylim = (sorted_energies[0] - 5., sorted_energies[3 * len(sorted_energies) / 4] + 5.)
                #xlim = (sorted_rmsds[0] - 5., sorted_rmsds[3 * len(sorted_rmsds) / 4] + 5.)
                xlim = (0, sorted_rmsds[-1] + 0.5)

                self.xlim = xlim
                self.ylim = ylim

                self.ax_plot.set_ylim(ylim)
                #self.ax_plot.set_xlim(xlim)

            for i in range(min(5, len(sorted_energy_rmsds))):
                self.ax_plot.plot(sorted_energy_rmsds[i][1], sorted_energy_rmsds[i][0], 'o', alpha=0.5) #'%so' % (sorted_energy_rmsds[i][2]), alpha=0.5)


            if len(self.energies[color]) > 2. and len(sorted_energies) > 4:
                for color in self.energies.keys():
                    try: 
                        #s = random.sample(sorted_energy_rmsds, min(len(sorted_energy_rmsds), 180))
                        s = sorted_energy_rmsds[: 3 * len(sorted_energy_rmsds) / 4]
                        s = random.sample(s, min(len(s), 180))

                        #self.create_contour_plot(np.array(r), np.array(e), self.ax_plot, xlim, ylim, color)
                    except Exception as ex:
                        print ("exception:", ex, "color:", color)

                        continue
                    
            for color in self.energies.keys():
                self.ax_plot.plot(self.rmsds[color], self.energies[color], 'o', alpha=0.5) #'%so' % (color), alpha=0.05)

        for color in self.energies.keys():
            xlim = (0, sorted_rmsds[-1] + 0.5)
            self.ax_hist.set_xlim(xlim)
            if len(self.rmsds[color])>2:
                self.ax_hist.hist(self.rmsds[color], color=color, alpha=0.5, normed=True)

        import matplotlib.pyplot as plt
        plt.draw()

    def diagnose_energy(self, energy_function, bgs):
        energies = [energy_function.eval_energy(cbm.SpatialModel(bg), background=True) for bg in bgs]

        return energies


    def finish(self):
        self.ax_plot.cla()
        sorted_energy_rmsds = sorted(self.energy_rmsds)

        sorted_energies = sorted([s[0] for s in sorted_energy_rmsds])
        sorted_rmsds = sorted([s[1] for s in sorted_energy_rmsds])

        se = sorted_energies[:3 * len(sorted_energies) // 4]
        sr = sorted_rmsds[:3 * len(sorted_rmsds) // 4]

        ylim = (sorted_energies[0] - 5., sorted_energies[3 * len(sorted_energies) // 4] + 5.)
        #xlim = (sorted_rmsds[0] - 5., sorted_rmsds[3 * len(sorted_rmsds) / 4] + 5.)
        xlim = (0, sorted_rmsds[3 * len(sorted_rmsds) // 4] + 5.)

        self.xlim = xlim
        self.ylim = ylim

        self.ax_plot.set_ylim(ylim)
        self.ax_plot.set_xlim(xlim)

        for i in range(min(5, len(sorted_energy_rmsds))):
            self.ax_plot.plot(sorted_energy_rmsds[i][1], sorted_energy_rmsds[i][0], 'o', alpha=0.5)
                    
        for color in self.energies.keys():
            self.ax_plot.plot(self.rmsds[color], self.energies[color], 'o', alpha=0.05)

        for color in self.energies.keys():
            self.create_contour_plot(np.array(self.rmsds[color]), np.array(self.energies[color]), self.ax_plot, self.xlim, self.ylim, color)

        import matplotlib.pyplot as plt
        plt.ioff()
        plt.show()


class SamplingStatistics:
    '''
    Store statistics about a sample.
    '''

    def __init__(self, sm_orig, plotter=None, plot_color=None, silent=False, output_file=sys.stdout, save_n_best=3, dists=[], no_rmsd=False, save_iterative_cg_measures=False):
        '''
        @param sm_orig: The original Spatial Model against which to collect statistics.
        '''
        self.energy_rmsd_structs = []
        self.counter = 0
        self.plotter = plotter
        self.plot_color = plot_color
        self.silent = silent
        self.verbose = False
        self.output_file = output_file
        self.save_n_best = save_n_best
        self.sm_orig = sm_orig
        self.energy_orig = None
        self.step_save = 0
        self.save_iterative_cg_measures = save_iterative_cg_measures



        self.dists = dists

        self.highest_rmsd = 0.
        self.lowest_rmsd = 10000000000.
        self.no_rmsd = no_rmsd
        self.creation_time = time.time()

        try:
            self.centers_orig = ftug.bg_virtual_residues(sm_orig.bg)        
            self.confusion_matrix_calculator = ftme.ConfusionMatrix(sm_orig.bg)
        except KeyError:
            # if there are no coordinates provided in the original
            # bulge graph file, then don't calculate rmsds
            self.centers_orig = None
            self.confusion_matrix_calculator = None


    def update_statistics(self, energy_function, sm, prev_energy, tracking_energies = None, tracked_energies=None):
        '''
        Add a newly sampled structure to the set of statistics.

        :param energy_function: The energy_function used to evaluate the structure.
        :param sm: The spatial model that was sampled.
        :param prev_energy: The evaluated (accepted) energy of the current step 
        :tracking_energyis: The energy_functions which are calculated for statistics, but not used for sampling.
        :tracked_energies: The energy values of the tracking_energies.
        '''
        self.counter += 1

        if self.energy_orig is None:
            self.energy_orig = 0.
            try:
                self.sm_orig.bg.add_all_virtual_residues()
                self.energy_orig = energy_function.eval_energy(self.sm_orig)
            except KeyError:
                # most likely no native structure was provided
                pass

        energy = prev_energy
        #energy = energy_function.eval_energy(sm, background=True)
        if energy_function.uses_background():
            energy_nobg = energy_function.eval_energy(sm, background=False)
        else:
            energy_nobg=energy

        mcc = None

        if self.centers_orig is not None:
            r = 0.
            if not self.no_rmsd:
                centers_new = ftug.bg_virtual_residues(sm.bg)
                r = cbr.centered_rmsd(self.centers_orig, centers_new)
                #r = cbr.drmsd(self.centers_orig, centers_new)
                cm = self.confusion_matrix_calculator.evaluate(sm.bg)
                mcc = ftme.mcc(cm)
        else:            
            # no original coordinates provided so we can't calculate rmsds
            r = 0.

        dist = None
        dist2 = None

        cg = sm.bg
        dists = []

        for (self.dist1, self.dist2) in self.dists:
            node1 = cg.get_node_from_residue_num(self.dist1)
            node2 = cg.get_node_from_residue_num(self.dist2)

            pos1, len1 = cg.get_position_in_element(self.dist1)
            pos2, len2 = cg.get_position_in_element(self.dist2)

            #fud.pv('node1, node2, pos1, pos2')

            vec1 = cg.coords[node1][1] - cg.coords[node1][0]
            vec2 = cg.coords[node2][1] - cg.coords[node2][0]

            #mid1 = (cg.coords[node1][0] + cg.coords[node1][1]) / 2
            #mid2 = (cg.coords[node2][0] + cg.coords[node2][1]) / 2

            mid1 = cg.coords[node1][0] + pos1 * (vec1 / len1)
            mid2 = cg.coords[node2][0] + pos2 * (vec2 / len2)
            
            #fud.pv('mid1, mid2')

            dists += [ftuv.vec_distance(mid1, mid2)]

        #self.energy_rmsd_structs += [(energy, r, sm.bg)]
        self.energy_rmsd_structs += [(energy_nobg, r, copy.deepcopy(sm.bg))]
        #self.energy_rmsd_structs += [(energy, r, sm.bg.copy())]

        sorted_energies = sorted(self.energy_rmsd_structs, key=lambda x: x[0])
        self.energy_rmsd_structs = sorted_energies[:self.save_n_best]

        if r > self.highest_rmsd:
            self.highest_rmsd = r

        if r < self.lowest_rmsd:
            self.lowest_rmsd = r

        lowest_energy = sorted_energies[0][0]
        lowest_rmsd = sorted_energies[0][1]

        '''
        if energy == lowest_energy:
            for key in sm.angle_defs:
                print >>sys.stderr, key, str(sm.angle_defs[key])
        '''

        if not self.silent:
            if self.verbose:
                '''
                for energy_func in energy_function.energies:
                    print energy_func.__class__.__name__, energy_func.eval_energy(sm)
                '''
            _, rog=fbe.length_and_rog(sm.bg)
            #output_str = u"native_energy [{:s} {:d}]: {:3d} {:5.03g} {:5.3f} ROG: {:5.3f} | min:
            output_str = u"native_energy [%s %d]: %3d %5.03g  %5.3f ROG: %5.3f | min: %5.2f (%5.2f) %5.2f | extreme_rmsds: %5.2f %5.2f (%.2f)" % ( sm.bg.name, sm.bg.seq_length, self.counter, energy, r , rog, lowest_energy, self.energy_orig, lowest_rmsd, self.lowest_rmsd, self.highest_rmsd, energy_nobg)
            output_str += " |"

            # assume that the energy function is a combined energy
            if isinstance(self.energy_function, fbe.CombinedEnergy):
                for e in self.energy_function.iterate_energies():
                    if isinstance(e,fbe.DistanceExponentialEnergy):
                        output_str += " [clamp {},{}: {:.1f}]".format(e.from_elem,
                                                                      e.to_elem,
                                                                      e.get_distance(sm))
            if tracked_energies and tracking_energies:
                output_str += " | [tracked Energies]"
                for i,e in enumerate(tracking_energies):
                    sn=e.shortname()
                    if len(sn)>12:
                        sn=sn[:9]+"..."
                    output_str += "  [{}]: ".format(sn)
                    output_str += "%5.03g" % (tracked_energies[i])
            elif tracking_energies:
                output_str += " | [tracked Energies]"
                for e in tracking_energies:
                    sn=e.shortname()
                    if len(sn)>12:
                        sn=sn[:9]+"..."
                    output_str += "  [{}]: ".format(sn)
                    output_str += "%5.03g" % (e.eval_energy(sm))

            if dist:
                output_str += " | dist %.2f" % (dist)

            for dist2 in dists:
                if dist2 is not None:
                    output_str += " | [dist2: %.2f]" % (dist2)

            if mcc is not None:
                output_str += " | [mcc: %.3f]" % (mcc)

            output_str += " [time: %.1f]" % (time.time() - self.creation_time)

            #Print to both STDOUT and the log file.
            if self.output_file != sys.stdout:
                print (output_str.strip())

            if self.output_file != None:
                print(output_str, file=self.output_file)
                self.output_file.flush()

        self.update_plots(energy, r)

        '''
        if self.counter % 1000 == 0:
            import pdb; pdb.set_trace()
        '''

        if self.counter % 10 == 0:
            if not self.silent:
                self.save_top(self.save_n_best, counter=self.counter)

        if self.step_save > 0 and self.counter % self.step_save == 0:
            #If a projection match energy was used, save the optimal projection direction to the file.
            if isinstance(self.energy_function, fbe.CombinedEnergy):
                for e in self.energy_function.iterate_energies():
                    if hasattr(e, "accepted_projDir"):
                        sm.bg.project_from=e.accepted_projDir
            sm.bg.to_cg_file(os.path.join(cbc.Configuration.sampling_output_dir, 'step%06d.coord' % (self.counter)))


    def save_top(self, n = 100000, counter=100, step_save=0):
        '''
        Save the top n structures.
        '''
        # if we don't want to save any structures, then don't save any structures
        if n == 0:
            return

        if n > len(self.energy_rmsd_structs):
            n = len(self.energy_rmsd_structs)

        sorted_energies = sorted(self.energy_rmsd_structs, key=lambda x: x[0])
        '''
        if self.save_iterative_cg_measures:
            self.energy_function.dump_measures(cbc.Configuration.sampling_output_dir, self.counter)
        else:
            self.energy_function.dump_measures(cbc.Configuration.sampling_output_dir)
        '''

        #self.energy_function.resample_background_kde(sorted_energies[0][2])

        for i in range(n):
            sorted_energies[i][2].to_cg_file(os.path.join(cbc.Configuration.sampling_output_dir, 'best%d.coord' % (i)))

        if self.step_save > 0:
            if self.counter % self.step_save == 0:
                sorted_energies[0][2].to_cg_file(os.path.join(cbc.Configuration.sampling_output_dir, 'intermediate_best%d.coord' % (counter)))

    def update_plots(self, energy, rmsd):
        '''
        Maintain plots of all the necessary statistics.
        '''
        if self.plotter != None:
            self.plotter.add_data(energy, rmsd, self.plot_color)
    
    def print_final_stats(self, energy_function):
        sorted_energies = sorted(self.energy_rmsd_structs, key=lambda x: x[0])
        sm = cbm.SpatialModel(sorted_energies[0][2])
        sm.get_sampled_bulges()

        print ("---------------------------")

        print ([e[1] for e in sorted_energies[:10]])

        '''
        for energy in energy_function.energies:
            print energy.__class__.__name__, energy.eval_energy(sm)
        '''

        print ("-------------------------")
        

class MCMCSampler:
    '''
    Sample using tradition accept/reject sampling.
    '''
    def __init__(self, sm, energy_function, stats, start_from_scratch=False, dump_measures=False):
        '''
        :param sm: SpatialModel that will be used for sampling.
    
        :param start_from_scratch: Boolean. If true, always sample stats. If false and stats are present (e.g. *.coord file), start at the native conformation.
        '''
        #BT: Seems to be not in used
        #if stats_type == 'continuous':
        #    self.cont_stats = cbs.ContinuousAngleStats(cbs.get_angle_stats())
        #elif stats_type == 'random':
        #    self.cont_stats = cbs.RandomAngleStats(cbs.get_angle_stats())
        #else:
        #    self.cont_stats = None
        
        self.step_counter = 0
        self.sm = sm
        self.energy_function = energy_function
        self.stats = stats
        if not isinstance(stats, sstats.SamplingStatistics):
            self.stats.energy_function = energy_function
        self.prev_energy = 100000000000.
        self.dump_measures = dump_measures
        self.resampled_energy = True

        print("INFO: Trying to load sampled elements.", file=sys.stderr)
        try:
            sm.load_sampled_elems()
        except:
            start_from_scratch=True
        else:
            resampled=False

        if start_from_scratch or not sm.elem_defs:  
            print("INFO: Starting with sampling of all stats.", file=sys.stderr)
            sm.sample_stats()
            resampled=True

        constraint_energy = sm.constraint_energy
        if sm.constraint_energy is not None or sm.junction_constraint_energy is not None:
            junction_constraint_energy = sm.junction_constraint_energy
            sm.constraint_energy = None
            sm.junction_constraint_energy = None
            print ("constraint energy about to build 1...", file=sys.stderr)
            sm.traverse_and_build()
            print ("constraint energy finished building 1", file=sys.stderr)
            sm.constraint_energy = constraint_energy
            sm.junction_constraint_energy = junction_constraint_energy
            print ("constraint energy about to build 2...", file=sys.stderr)
            sm.traverse_and_build(verbose=not resampled)
            print ("constraint energy finished building 2", file=sys.stderr)
            self.energy_function.energies += sm.constraint_energy.energies
            self.energy_function.energies += [sm.junction_constraint_energy]
        sm.constraint_energy = None
        sm.junction_constraint_energy = None

        sm.traverse_and_build()
        self.prev_energy = energy_function.eval_energy(sm)
        try:
            self.prev_constituing = self.energy_function.constituing_energies
        except AttributeError: 
            pass
        #Accept the measure of the initial structure.
        #This is required so reject_last_measure does not accept the last measure from the 
        #file a second time.
        self.energy_function.accept_last_measure()
        sm.get_sampled_bulges()
        if isinstance(stats, sstats.SamplingStatistics):
            self.stats.print_header()

    def change_elem(self):
        '''
        Change a random element and accept the change with a probability
        proportional to the energy function.
        '''
        # pick a random element and get a new statistic for it
        possible_elements=list(self.sm.bg.get_mst())
        pe=set(possible_elements)
        d = random.choice(possible_elements)

        #import pdb
        #pdb.set_trace()
        possible_stats=self.sm.conf_stats.sample_stats(self.sm.bg, d)
        new_stat = random.choice(possible_stats)

        # we have to replace the energy because we've probably re-calibrated
        # the energy function
        if self.resampled_energy and self.energy_function.uses_background():
            #print("CHANGE ELEMENT: EVALUATING PREVIOUS ENERGY FOR self.energy_function")
            self.prev_energy = self.energy_function.eval_energy(self.sm, background=True)
            try:
                self.prev_constituing =  self.energy_function.constituing_energies
            except AttributeError: pass
            self.resampled_energy = False

        prev_stat = self.sm.elem_defs[d]


        self.sm.elem_defs[d] = new_stat
        self.sm.traverse_and_build(start=d)
        energy = self.energy_function.eval_energy(self.sm, background=True)

        # self.stats.sampled_energy = energy

        #print("Energy is {}, prev_energy is {} ...".format(energy, self.prev_energy), end="\n")
        if energy < self.prev_energy:
            # lower energy means automatic acceptance accordint to the
            # metropolis hastings criterion
            self.prev_energy = energy
            try:
                self.prev_constituing =  self.energy_function.constituing_energies
            except AttributeError: pass
            self.energy_function.accept_last_measure()
            #print ("...accepting")
        else:
            # calculate a probability
            r = random.random()
            if r > math.exp(self.prev_energy - energy):
                # reject the sampled statistic and replace it the old one
                self.sm.elem_defs[d] = prev_stat
                self.sm.traverse_and_build(start='start')
                # self.stats.sampled_energy = self.prev_energy
                self.energy_function.reject_last_measure()
                #print ("...rejecting")
            else:
                # accept the new statistic
                self.prev_energy = energy
                try:
                    self.prev_constituing =  self.energy_function.constituing_energies
                except AttributeError: pass
                self.energy_function.accept_last_measure()
                #print ("...still accepting")

    def step(self):
    
        self.change_elem()
        if isinstance(self.energy_function, fbe.CombinedEnergy):
            for e in self.energy_function.iterate_energies():
                if hasattr(e, "accepted_projDir"):
                    self.sm.bg.project_from=e.accepted_projDir
        
        if self.dump_measures:
            if self.step_counter % 20 == 0:
                self.energy_function.dump_measures(cbc.Configuration.sampling_output_dir, 
                                                   self.step_counter)

        if self.step_counter % 3 == 0:
            self.resampled_energy = True
            self.energy_function.resample_background_kde(self.sm.bg)

        self.step_counter += 1
        if isinstance(self.stats, sstats.SamplingStatistics):
            self.stats.update_statistics( self.sm, self.prev_energy[0], self.prev_constituing )

        self.energy_function.update_adjustment(self.step_counter, self.sm.bg)


class GibbsBGSampler:
    '''
    A Gibbs Sampler for Bulge Graphs.
    '''

    def __init__(self, sm, energy_function, stats):
        '''
        param @sm: SpatialModel that will be used for sampling.
        '''
        self.sm = sm
        self.energy_function = energy_function
        self.stats = stats
        self.angles_to_sample = 50

        sm.sample_stats()
        sm.get_sampled_bulges()

    def step(self):
        '''
        Perform another step in the simulation.
        '''

        self.sm.sample_stems()
        self.sm.sample_loops()
        self.sm.traverse_and_build()

        # pick a random bulge to vary
        #bulge = self.sm.bg.get_random_bulge()
        (bulge, ang_type1) = random.choice(self.sm.sampled_bulge_sides)
        dims = self.sm.bg.get_bulge_dimensions(bulge)
        
        # What are the potential angle statistics for it
        (dist, size1, size2, type1) = cbs.get_angle_stat_dims(dims[0], dims[1], ang_type1)[0]
        possible_angles = cbs.get_angle_stats()[(size1, size2, ang_type1)]

        # only choose 10 possible angles
        if len(possible_angles) > self.angles_to_sample:
            possible_angles = random.sample(possible_angles, self.angles_to_sample)

        #possible_angles += [self.sm.angle_defs[bulge][ang_type1]]
        energies = dict()

        # evaluate the energies of the structure when the original
        # angle is replaced by one of the 10 potential new ones
        for pa in possible_angles:
            self.sm.angle_defs[bulge][ang_type1] = pa
            self.sm.traverse_and_build(start=bulge)
            energy = self.energy_function.eval_energy(self.sm, background=True)
            energies[pa] = energy


        # energy = -log(p(S)) 
        # So... we want to maximize p(S)
        # Therefore, we want to minimize the energy
        max_energy = max(energies.values())
        min_energy = min(energies.values())

        if max_energy - min_energy > 40:
            max_energy = min_energy + 40.

        for pa in possible_angles:
            prev_energy = energies[pa]
            if prev_energy > max_energy:
                prev_energy = max_energy 
            
            prev_energy = prev_energy - min_energy
            energies[pa] = np.exp(-prev_energy)

        # Convert all of the sampled energies into one probability
        total_energy = sum([energies[key] for key in energies.keys()])

        energy_probs = dict()
        for key in energies.keys():
            energy_probs[key] = energies[key] / total_energy

        # sanity check
        #assert(allclose(total_prob, 1.))

        #pick one new angle to accept given the probabilities of the
        #sampled ones
        prob_remaining = 1.
        for key in energy_probs.keys():
            if random.random() < energy_probs[key] / prob_remaining:
                self.sm.angle_defs[bulge][ang_type1] = key
                #self.sm.traverse_and_build(start=bulge)
                break

            prob_remaining -= energy_probs[key]

        self.sm.traverse_and_build(start=bulge)
        self.stats.update_statistics(self.energy_function, self.sm)


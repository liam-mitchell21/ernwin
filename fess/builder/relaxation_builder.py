import fess.builder.energy as fbe
import networkx as nx
import logging

log = logging.getLogger(__name__)

def get_sm_bad_bulges(sm):
    bad_bulges = []
    for ml in sm.bg.mloop_iterator():
        if ml in sm.bg.mst:
            continue
        if ml in sm.junction_constraint_energy:
            if ml in sm.elem_defs:
                sampled_stats={ml:sm.elem_defs[ml]}
            else:
                sampled_stats=None
            ej = sm.junction_constraint_energy[ml].eval_energy( sm.bg, sampled_stats = sampled_stats, nodes=[ml] )
            if ej>0:
                bad_bulges.extend(l for l in sm.junction_constraint_energy[ml].bad_bulges if l not in sm.bg.mst)
    return bad_bulges


def relax_sm(sm, stat_source, fixed_loops=[]):
    movestring=""
    try:
        bad_bulges = get_sm_bad_bulges(sm)

        # Loops that are already ok
        correct_loops = [ m for m in sm.bg.mloop_iterator()
                                if m not in sm.bg.mst
                                and m not in bad_bulges]
        fixed_loops.extend(sm.frozen_elements)
        cycles = get_mst_cycles(sm.bg)
        log.info("BB: %s ", bad_bulges)
        while bad_bulges:
            brokenloop = get_loop_with_smallest_cycle(bad_bulges, cycles)
            # Free stats are ONLY in the cycle we try to fix.
            correct_loop_elements = []
            log.info("Correct loops: %s", correct_loops)
            for cl in correct_loops:
                correct_loop_elements.extend(cycles[cl])
            free_stats = [ elem for elem in cycles[brokenloop]
                                if elem not in correct_loop_elements
                                and elem not in fixed_loops
                         ]
            brokenloops=[brokenloop]
            # If 2 loops have the same cycle, they can only be fixed together!
            for b in bad_bulges:
                if b!=brokenloop and cycles[brokenloop]==cycles[b]:
                    brokenloops.append(b)
            log.info("broken %s, Cycle %s: Free: %s", brokenloops, cycles[brokenloop], free_stats)
            if not free_stats:
                log.info("No degrees of freedom for %s", brokenloops)
                return False, movestring+"{}XimmoveableX;".format(brokenloops[0])
            for (s1,elem,s2) in sm.bg.build_order:
                if elem in free_stats:
                    lastmove = do_gradient_walk(sm, brokenloops, elem,
                                           stat_source, clash_nodes=cycles[brokenloops[0]])
                    movestring+=lastmove
                    bad_bulges = get_sm_bad_bulges(sm)
                    log.info("After gradientwalk: bad_bulges=%s", bad_bulges)
                    if not set(brokenloops) & set(bad_bulges):
                        correct_loops.extend(brokenloops)
                        break
            else:
                log.info("Could not fix %s", brokenloops)
                return False, movestring+"XbadjunxtionsX"
        bad_bulges = get_sm_bad_bulges(sm)
        assert bad_bulges==[]
        with open("loops_work.cg", "w") as f:
            f.write(sm.bg.to_cg_string())
        ok, lastmove = fix_clashes(sm, stat_source, fixed_loops)
        movestring+=lastmove
        return ok, movestring
    except KeyboardInterrupt:
        log.error("Movestring (junction) so far: %s", movestring)
        raise

def fix_clashes(sm, stat_source, externally_fixed_elems):
    movestring=""
    try:
        sm.constraint_energy.eval_energy(sm.bg)
        clash_pairs = list(map(tuple, sm.constraint_energy.bad_bulges))
        log.info("Clashes: %s", clash_pairs)
        # Do not open the multiloops.
        cycles = get_mst_cycles(sm.bg)
        fixed_elems = [elem for cycle in cycles.values() for elem in cycle]
        fixed_elems.extend(externally_fixed_elems)
        clash_paths = get_clash_paths(sm.bg, clash_pairs)
        log.info("Fixed elements: %s", fixed_elems)
        for cp, path in clash_paths.items():
            if all(e in fixed_elems for e in path if e[0]!="s"):
                log.info("Cannot remove clash %s. No degrees of freedom", cp)
                return False, movestring+"{}XimmoveableX{};".format(*cp)
        while clash_pairs:
            # Start by fixing the clash-pair with fewest elements in between.
            # Using the energy, we also try to minimize the other clashes as
            # secondary objective.
            pair = get_loop_with_smallest_cycle(clash_pairs, clash_paths)
            for (s1,loop,s2) in sm.bg.build_order:
                if loop in clash_paths[pair] and loop not in fixed_elems:
                    lastmove = do_clash_gradient_walk(sm, pair, loop, stat_source)
                    movestring+=lastmove
                    sm.constraint_energy.eval_energy(sm.bg)
                    clash_pairs = list(map(tuple, sm.constraint_energy.bad_bulges))
                    clash_paths = get_clash_paths(sm.bg, clash_pairs)
                    if pair not in clash_pairs:
                        # For clashes, we do not fix the loop, because it might
                        # be required for another clash pair.
                        # In the gradient walk we disallow (re)introduction of
                        # clash_pairs anyway.
                        break
            else:
                log.info("Could not fix clash %s", pair)
                return False, movestring+"XclashesX;"
        sm.constraint_energy.eval_energy(sm.bg)
        clash_pairs = sm.constraint_energy.bad_bulges
        assert clash_pairs==[]
        bad_bulges = get_sm_bad_bulges(sm)
        assert bad_bulges==[]
        return True, movestring
    except KeyboardInterrupt:
        log.error("Movestring (clash) so far: %s", movestring)
        raise


def get_junction_energies(sm, bad_bulges):
    log.debug("Getting junction energies for %s: %s", bad_bulges, {k: v.shortname for k,v in sm.junction_constraint_energy.items()})
    energies=[]
    vals = []
    for elem in bad_bulges:
        e = sm.junction_constraint_energy[elem]
        log.debug("Energy(%s) = %s", elem, e.shortname)
        if hasattr(e, "_other_energy"):
            if e._shortname=="MAX":
                vals.append(e.adjustment)
            e=e._other_energy
        energies.append(e)
    if not vals:
        vals=[0]
    return fbe.CombinedEnergy(energies), min(vals)


def count_cycles(cycles, loop):
    count=0
    for c in cycles.values():
        if loop in c:
            count+=1
    return count

def count_smaller_equal_cycles(cycles, loop, length):
    count=0
    for c in cycles.values():
        if loop in c and len(c)<=length:
            count+=1
    return count

def get_mst_cycles(bg):
    cycles={}
    bg.traverse_graph()
    for loop in bg.mloop_iterator():
        if loop not in bg.mst:
            cycles[loop]=get_mloop_mst_cycle(bg, loop)
    return cycles

def get_mloop_mst_cycle(bg, loop):
    v1,v2 = bg.edges[loop]
    G = mst_to_nx(bg)
    return nx.shortest_path(G,v1,v2)

def mst_to_nx(bg):
    G = nx.Graph()
    for node in bg.mst:
        G.add_node(node)
        for neighbor in bg.edges[node]:
            if neighbor in bg.mst:
                G.add_edge(node, neighbor)
    return G

def get_loop_with_smallest_cycle(loops, cycles):
    return min(loops, key=lambda x:len(cycles[x]))

def do_gradient_walk(sm, brokenloops, elem, stat_source, clash_nodes=[]):
    energy_function, max_val = get_junction_energies(sm, brokenloops)
    energy = energy_function.eval_energy(sm.bg, nodes=brokenloops)
    sm.constraint_energy.eval_energy(sm.bg, nodes=clash_nodes)
    clash_pairs = sm.constraint_energy.bad_bulges


    log.info("Gradient walk for %s (broken %s): Original Energy (%s): %s, original clash_pairs: %s",
                    elem, brokenloops, energy_function.shortname, energy, clash_pairs)
    best_stat = sm.elem_defs[elem]
    prev_name=best_stat.pdb_name
    any_moved=False
    # If all broken-loops have the same cycle, they require the same number of steps
    steps=count_build_steps(elem, brokenloops[0], sm.bg)
    for stat in stat_source.iterate_stats_for(sm.bg, elem):
        sm.elem_defs[elem]=stat
        sm.new_traverse_and_build(start=elem, max_steps=steps, include_start=True)
        e2 = energy_function.eval_energy(sm.bg, nodes=brokenloops)
        sm.constraint_energy.eval_energy(sm.bg, nodes=clash_nodes)
        new_clash_pairs = sm.constraint_energy.bad_bulges
        if (set(new_clash_pairs)<set(clash_pairs)
            or (e2<energy and set(new_clash_pairs)==set(clash_pairs) and energy>=max_val)):
            any_moved=True
            clash_pairs=new_clash_pairs
            energy=e2
            log.info("Gradient walk for %s (broken %s): Intermediate Energy: %s,"
                     "clash_pairs: %s", elem, brokenloops, energy, clash_pairs)
            best_stat = stat
            if energy<=max_val and not clash_pairs:
                break
    sm.elem_defs[elem]=best_stat
    sm.new_traverse_and_build()
    log.info("Gradient walk for %s (broken %s): Final Energy: %s, clash_pairs: %s", elem, brokenloops, energy, clash_pairs)
    if any_moved:
        movestring= "{}:{}->{};".format(elem, prev_name, best_stat.pdb_name)
    else:
        movestring=""
    return movestring

def do_clash_gradient_walk(sm, clash_pair, loop, stat_source):
    energy = sm.constraint_energy.eval_energy(sm.bg)
    all_clash_pairs = sm.constraint_energy.bad_bulges
    log.info("Gradient walk for %s (clash %s): Original Energy (%s): %s, original clashpairs: %s",
              loop, clash_pair, sm.constraint_energy.shortname, energy, all_clash_pairs)
    last_clash_pairs = all_clash_pairs
    best_stat = sm.elem_defs[loop]
    prev_name=best_stat.pdb_name
    any_moved=False
    steps=count_build_steps_stems(loop, clash_pair, sm.bg)
    for stat in stat_source.iterate_stats_for(sm.bg, loop):
        sm.elem_defs[loop]=stat
        sm.new_traverse_and_build(start=loop, max_steps=steps, include_start=True)
        e2 = sm.constraint_energy.eval_energy(sm.bg)
        new_clash_pairs = sm.constraint_energy.bad_bulges
        if set(new_clash_pairs)-set(all_clash_pairs):
            # Never introduce new clashes
            continue

        if clash_pair in last_clash_pairs and clash_pair not in new_clash_pairs:
            # Accept removal of desired clash pair,
            # even if it reintroduces a clash-pair from all_clash_pairs
            log.info("Gradient walk for %s (clash %s): Intermediate Energy (%s): %s, "
                     "removed target clashpair %s, clashpairs now: %s",
                     loop, clash_pair, sm.constraint_energy.shortname, e2,
                     clash_pair,
                     new_clash_pairs)
        elif set(new_clash_pairs)<set(last_clash_pairs):
            # Accept removal of a clash-pair, even if it increases the clash energy
            log.info("Gradient walk for %s (clash %s): Intermediate Energy (%s): %s, "
                     "removed other clashpair(s), now: %s",
                     loop, clash_pair, sm.constraint_energy.shortname, e2,
                     new_clash_pairs)
        elif  set(new_clash_pairs)==set(last_clash_pairs) and e2<energy:
            # If clash-pairs do not change, use energy
            log.info("Gradient walk for %s (clash %s): Decreased energy (%s): %s",
                     loop, clash_pair, sm.constraint_energy.shortname, e2)
        else:
            # No improvement
            continue
        energy=e2
        best_stat = stat
        last_clash_pairs = new_clash_pairs
        any_moved=True
        if energy==0:
            break
    sm.elem_defs[loop]=best_stat
    sm.new_traverse_and_build()
    log.info("Gradient walk for %s (clash %s): Final energy (%s): %s, final clash_pairs: %s",
             loop, clash_pair, sm.constraint_energy.shortname, e2, last_clash_pairs)
    if any_moved:
        movestring= "{}:{}->{};".format(loop, prev_name, best_stat.pdb_name)
    else:
        movestring=""
    return movestring

def count_build_steps_stems(elem, stems, bg):
    found=None
    for s1, l, s2 in bg.build_order:
        if elem in [s1, l]:
            found=1
        elif found is not None:
            found+=1
        if found and s2 in stems:
            break
    return found


def count_build_steps(loop, broken_loop, bg):
    return count_build_steps_stems(loop, bg.edges[broken_loop], bg)


def get_clash_paths(bg, clash_pairs):
    paths={}
    for s1,s2  in clash_pairs:
        paths[(s1,s2)]=get_single_clash_path(bg, s1, s2)
    return paths

def get_single_clash_path(bg, s1, s2):
    G = mst_to_nx(bg)
    return nx.shortest_path(G,s1,s2)
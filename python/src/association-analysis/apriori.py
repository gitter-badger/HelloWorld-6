#!/usr/bin/env python
# -*- coding: utf-8 -*-
# (c) 2014 Everaldo Aguiar & Reid Johnson
#
# Modified from:
# Marcel Caraciolo (https://gist.github.com/marcelcaraciolo/1423287)
#
# Functions to compute and extract association rules from a given frequent
# itemset generated by the Apriori algorithm.
import os
import sys
import logging
import datetime
import multiprocessing
import queue

import pandas as pd


N_PROCESS = 7
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
ch.setFormatter(formatter)
log.addHandler(ch)


def apriori(dataset, min_support=0.5, min_hconf=0.5):
    """Implements the Apriori algorithm.

    The Apriori algorithm will iteratively generate new candidate
    k-itemsets using the frequent (k-1)-itemsets found in the previous
    iteration.

    Parameters
    ----------
    dataset : list
        The dataset (a list of transactions) from which to generate
        candidate itemsets.

    min_support : float
        The minimum support threshold. Defaults to 0.5.

    Returns
    -------
    F : list
        The list of frequent itemsets.

    support_data : dict
        The support data for all candidate itemsets.

    References
    ----------
    .. [1] R. Agrawal, R. Srikant, "Fast Algorithms for Mining Association
           Rules", 1994.

    """
    C1 = create_candidates(dataset)
    D = list(map(set, dataset))
    support_data = {}

    F1 = support_prune(D, C1, min_support, min_hconf,
                       support_data)
    F = [F1]
    k = 2
    while (len(F[k - 2]) > 0):
        Ck = apriori_gen(F[k - 2], k, support_data, min_hconf)
        if len(Ck) == 0:
            log.debug('no candidates')
            break

        Fk = support_prune(D, Ck, min_support, min_hconf,
                           support_data)
        F.append(Fk)
        k += 1

    return F, support_data


def create_candidates(dataset):
    """Creates a list of candidate 1-itemsets from a list of transactions.

    Parameters
    ----------
    dataset : list
        The dataset (a list of transactions) from which to generate candidate
        itemsets.

    Returns
    -------
    The list of candidate itemsets (c1) passed as a frozenset (a set that is
    immutable and hashable).
    """
    log.info('create_candidates')

    c1 = set([])
    for transaction in dataset:
        c1.update(transaction)

    return [frozenset([_]) for _ in c1]


def calc_supp_worker(dataset_q, candidates, sscnt, cand_len,
                     n_all_dataset, n_finished):
    while not dataset_q.empty():
        try:
            dataset = dataset_q.get(timeout=0.1)
        except queue.Empty:
            pass
        if len(dataset) < cand_len:
            with n_finished.get_lock():
                n_finished.value += 1
            continue

        for cand, idx in candidates.items():
            if cand.issubset(dataset):
                with sscnt.get_lock():
                    sscnt[idx] += 1

        with n_finished.get_lock():
            n_finished.value += 1
            log.debug('{}/{} pid {} calculate dataset'
                      .format(n_finished.value, n_all_dataset.value,
                              os.getpid()))


def support_prune(dataset, candidates, min_support, min_hconf,
                  support_data):
    """Returns all candidate itemsets that meet a minimum support threshold.

    By the apriori principle, if an itemset is frequent, then all of its
    subsets must also be frequent. As a result, we can perform support-based
    pruning to systematically control the exponential growth of candidate
    itemsets. Thus, itemsets that do not meet the minimum support level are
    pruned from the input list of itemsets (dataset).

    Parameters
    ----------
    dataset : list
        The dataset (a list of transactions) from which to generate candidate
        itemsets.

    candidates : frozenset
        The list of candidate itemsets.

    min_support : float
        The minimum support threshold.

    support_data : dict
        The support data for all candidate itemsets.

    Returns
    -------
    retlist : list
        The list of frequent itemsets.

    """
    log.info('support_prune with min_supp {}, min_hconf {}'
             .format(min_support, min_hconf))

    # updata support data
    log.debug('calculate support')
    n_all_items = len(dataset)
    len_each_cand = len(list(candidates.keys())[0])

    candidates = {
        cand: i
        for i, cand in enumerate(candidates)
    }
    n_all_dataset = multiprocessing.Value('i', len(dataset))
    n_finished = multiprocessing.Value('i', 0)
    sscnt = multiprocessing.Array('i', len(candidates))
    m = multiprocessing.Manager()
    dataset_q = m.Queue()
    candidates = m.dict(candidates)
    list(map(dataset_q.put, dataset))
    procs = [
        multiprocessing.Process(target=calc_supp_worker,
                                args=(dataset_q, candidates, sscnt,
                                      len_each_cand,
                                      n_all_dataset, n_finished))
        for _ in range(N_PROCESS)
    ]
    [p.start() for p in procs]
    [p.join() for p in procs]

    sscnt = {
        cand: sscnt[idx]
        for cand, idx in candidates.items()
    }

    log.debug('calculate hconf')
    # total number of transactions in the dataset
    retlist = []  # array for unpruned itemsets
    for cand, n_supp in sscnt.items():
        # Calculate the support of itemset cand.
        support = n_supp / n_all_items

        if len_each_cand > 1:
            # Calculate h-confidence
            hconf = support / max(map(support_data.get,
                                      [frozenset([_]) for _ in cand]))
        else:
            hconf = 1

        support_data[cand] = support

        if support >= min_support and hconf >= min_hconf:
            log.debug('save cand: {}'.format(cand))
            retlist.append(cand)

    return retlist


def apriori_gen_worker(freq_q, n_freq):
    pass


def apriori_gen(freq_sets, k, support_data, min_hconf):
    """Generates candidate itemsets (via the F_k-1 x F_k-1 method).

    This operation generates new candidate k-itemsets based on the frequent
    (k-1)-itemsets found in the previous iteration. The candidate generation
    procedure merges a pair of frequent (k-1)-itemsets only if their first k-2
    items are identical.

    Parameters
    ----------
    freq_sets : list
        The list of frequent (k-1)-itemsets.

    k : integer
        The cardinality of the current itemsets being evaluated.

    Returns
    -------
    retlist : list
        The list of merged frequent itemsets.
    """
    log.info('apriori_gen for k {}'.format(k))

    retList = []  # list of merged frequent itemsets
    lenLk = len(freq_sets)  # number of frequent itemsets
    freq_sets = [sorted(i) for i in freq_sets]
    for i in range(lenLk):
        a = freq_sets[i]
        F1 = a[: k - 2]  # first k-2 items of freq_sets[i]
        for j in range(i + 1, lenLk):
            b = freq_sets[j]
            F2 = b[: k - 2]  # first k-2 items of freq_sets[j]

            # check cross-support property
            if k > 2:
                max_supp = max(map(support_data.get,
                                   [frozenset([_]) for _ in a]))
                min_supp = min(map(support_data.get,
                                   [frozenset([_]) for _ in b]))
                upper_bound = min_supp / max_supp
                if upper_bound < min_hconf:
                    log.debug('prune by cross-support property')
                    continue

            if F1 == F2:  # if the first k-2 items are identical
                # Merge the frequent itemsets.
                retList.append(frozenset(a) | frozenset(b))

    return retList


def rules_from_conseq(freq_set, H, support_data, rules,
                      min_confidence=0.5):
    """Generates a set of candidate rules.

    Parameters
    ----------
    freq_set : frozenset
        The complete list of frequent itemsets.

    H : list
        A list of frequent itemsets (of a particular length).

    support_data : dict
        The support data for all candidate itemsets.

    rules : list
        A potentially incomplete set of candidate rules above the minimum
        confidence threshold.

    min_confidence : float
        The minimum confidence threshold. Defaults to 0.5.
    """
    m = len(H[0])
    if m == 1:
        Hmp1 = calc_confidence(freq_set, H, support_data,
                               rules, min_confidence)
    if (len(freq_set) > (m + 1)):
        Hmp1 = apriori_gen(H, m + 1)  # generate candidate itemsets
        Hmp1 = calc_confidence(freq_set, Hmp1, support_data,
                               rules, min_confidence)
        if len(Hmp1) > 1:
            # If there are candidate rules above the minimum confidence
            # threshold, recurse on the list of these candidate rules.
            rules_from_conseq(freq_set, Hmp1, support_data, rules,
                              min_confidence)


def calc_confidence(freq_set, H, support_data, rules, min_confidence=0.5):
    """Evaluates the generated rules.

    One measurement for quantifying the goodness of association rules is
    confidence. The confidence for a rule 'P implies H' (P -> H) is defined as
    the support for P and H divided by the support for P
    (support (P|H) / support(P)), where the | symbol denotes the set union
    (thus P|H means all the items in set P or in set H).

    To calculate the confidence, we iterate through the frequent itemsets and
    associated support data. For each frequent itemset, we divide the support
    of the itemset by the support of the antecedent (left-hand-side of the
    rule).

    Parameters
    ----------
    freq_set : frozenset
        The complete list of frequent itemsets.

    H : list
        A list of frequent itemsets (of a particular length).

    min_support : float
        The minimum support threshold.

    rules : list
        A potentially incomplete set of candidate rules above the minimum
        confidence threshold.

    min_confidence : float
        The minimum confidence threshold. Defaults to 0.5.

    Returns
    -------
    pruned_H : list
        The list of candidate rules above the minimum confidence threshold.
    """
    # list of candidate rules above the minimum confidence threshold
    pruned_H = []
    for conseq in H:  # iterate over the frequent itemsets
        conf = support_data[freq_set] / support_data[freq_set - conseq]
        if conf >= min_confidence:
            rules.append((freq_set - conseq, conseq, conf))
            pruned_H.append(conseq)

    return pruned_H


def generate_rules(F, support_data, min_confidence=0.5):
    """Generates a set of candidate rules from a list of frequent itemsets.

    For each frequent itemset, we calculate the confidence of using a
    particular item as the rule consequent (right-hand-side of the rule). By
    testing and merging the remaining rules, we recursively create a list of
    pruned rules.

    Parameters
    ----------
    F : list
        A list of frequent itemsets.

    support_data : dict
        The corresponding support data for the frequent itemsets (L).

    min_confidence : float
        The minimum confidence threshold. Defaults to 0.5.

    Returns
    -------
    rules : list
        The list of candidate rules above the minimum confidence threshold.
    """
    rules = []
    for i in range(1, len(F)):
        for freq_set in F[i]:
            H1 = [frozenset([itemset]) for itemset in freq_set]
            if (i > 1):
                rules_from_conseq(freq_set, H1, support_data, rules,
                                  min_confidence)
            else:
                calc_confidence(freq_set, H1, support_data, rules,
                                min_confidence)

    return rules


def load_movie_data():
    dataset = pd.read_csv(
        # '/Users/laisky/repo/caigen-lab/consume-analysis/data/ratings.dat',
        '../data/ratings.dat',
        sep='::', parse_dates=['time'],
        date_parser=lambda ts: datetime.datetime.fromtimestamp(int(ts))
    )[['user', 'movie', 'rate']]
    dataset = dataset[dataset['rate'] > 3][['user', 'movie']].\
        groupby(['user'], as_index=False).\
        agg(lambda vals: tuple(vals))

    dataset = dataset['movie']
    return dataset


def load_b2b_data():
    dataset = pd.read_csv(
        '/Users/laisky/repo/caigen-lab/consume-analysis/data/b2b_总价(不含税).csv',
        encoding='utf-8', parse_dates=['确认时间']
    )

    dataset = dataset[['客户名称', '产品名称', '系统合同号']]
    dataset['产品名称'] = pd.factorize(dataset['产品名称'])[0]
    dataset = dataset.groupby(['客户名称', '系统合同号'], as_index=False).\
        agg(lambda vals: tuple(set(vals)))['产品名称']
    return dataset


def main(min_conf=0.5):
    logging.basicConfig(filename='apriori_{:1.2f}.log'.format(min_conf),
                        level=logging.DEBUG)
    # import numpy as np
    # dataset = np.random.exponential(scale=10, size=(1000, 10)).\
    #     astype(np.int64)
    # dataset = load_b2b_data()
    # dataset = load_movie_data()
    dataset = pd.read_pickle(
        # '/Users/laisky/repo/caigen-lab/consume-analysis/data/b2b.pkl'
        '../data/b2b.pkl'
    )
    r = apriori(dataset, min_support=0.00009, min_hconf=min_conf)
    log.info('min_conf: {}'.format(min_conf))
    log.info(sum([len(_) for _ in r[0]]))
    # pprint.pprint(r[0])


if __name__ == '__main__':
    # parser = argparse.ArgumentParser()
    # parser.add_argument('-c', '--conf', type=float)
    # args = parser.parse_args()
    # main(args.conf)

    main()

from __future__ import division

import Orange,orngTree
import os
import sys
import random


from partridge.config import config
from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy

from matplotlib import pyplot as plt

from partridge.models import db
from partridge.models.doc import Paper, PaperFile, Sentence, C_ABRV



app = Flask(__name__)
app.config.update(config)

db.app = app
db.init_app(app)

TYPE_DIRS = {
    "Review"     : "/home/james/dissertation/papers_for_type/review",
    "Research"   : "/home/james/dissertation/papers_for_type/research",
    "Case Study" : "/home/james/dissertation/papers_for_type/case", 
    #"Subjective" : "/home/james/dissertation/papers_for_type/subjective",
    "Essay"      : "/home/james/dissertation/papers_for_type/essay",
    "OpinionSuper": "/home/james/dissertation/papers_for_type/view_per_op",
    #"Opinion"    : "/home/james/dissertation/papers_for_type/opinion",
    #"Perspective": "/home/james/dissertation/papers_for_type/perspective",
    #"Viewpoint"  : "/home/james/dissertation/papers_for_type/viewpoints",
    #"Synopsis"   : "/home/james/dissertation/papers_for_type/synopsis",
    "Correspondence" : "/home/james/dissertation/papers_for_type/correspondence"
}


#set up data domain
class_var = Orange.feature.Discrete("type")

for type in TYPE_DIRS:
    class_var.add_value(type)

FEATURES = C_ABRV.keys()

domain = Orange.data.Domain(
        [Orange.feature.Continuous(x) for x in FEATURES], class_var)

def build_papers_table():
    """Given TYPE_DIRS, create an Orange Table using paper data from db"""

    types = {}
    for paper_type in TYPE_DIRS:
        types[paper_type] = set(find_paper_ids(TYPE_DIRS[paper_type]))
        
        print "Found %d %s papers" % (len(types[paper_type]), paper_type)
        

    all_ids = set()

    for type in types:
        all_ids |= types[type]

    print "Found %d papers in total" % len(all_ids)
    
    paper_table = Orange.data.Table(domain)
    print "Loading Data..."

    offset = 0
    limit = 50
    
    q = Paper.query.filter(Paper.id.in_(all_ids))

    while q.offset(offset).limit(limit).count() > 0:

        print "Downloading batch of %d papers..." % limit

        for paper in q.offset(offset).limit(limit).all():
            if len(paper.sentences) < 1:
                continue

            inst_list = []
            sentdist = paper.sentenceDistribution(True)
            for coresc in FEATURES:
                inst_list.append( sentdist[coresc] * 100 / len(paper.sentences) )

            for type in types:
                if paper.id in types[type]:
                    inst_list.append(type)
                    break
                
            inst = Orange.data.Instance(domain, inst_list)
            paper_table.append(inst)

            del paper

        offset += limit

    #return the table to the caller
    return paper_table


def find_paper_ids( dir ):

    ids = []

    for root, dirs, files in os.walk(dir):
        
        for file in files:
            name,ext = os.path.splitext(file)

            if ext == ".xml":
                pfile = PaperFile.query.filter(
                    PaperFile.path.like("%%%s%%" % name)).first()

                if(pfile != None):
                    ids.append(pfile.paper_id)

    return ids


def printConfusion(confusion,classes):
    cs = sorted(classes)
    print 'conf\t\t' + '\t\t'.join(cs)
    for c in cs:
        sys.stdout.write(c)
        for p in cs:
            sys.stdout.write('\t\t' + str(confusion[c][p]))
        print
    print

def printMeasures( confusion ):
    
    print "Class\t\tRecall\t\tPrecision\t\tF-measure"
    print "-----------------------------------------------"

    for c in sorted(confusion):
        recall  = confusion[c][c] / sum(confusion[c].values())


        fp = sum( [ klass[c] for klass in confusion.values()])

        
        if( (confusion[c][c] > 0) and (fp > 0) ):
            prec = confusion[c][c] / fp
        else:
            prec = 0

        
        if( (prec > 0) or (recall > 0)):
            fm     = (2 * prec * recall) / (prec + recall)
        else:
            fm     = 0

        print "%s\t\t%f\t\t%f\t\t%f" % ( c, recall, prec, fm)


#---------------------------------------------------------------
    
def printResults(tabledata, tree, classes):
    confusion = buildConfusion(tabledata, tree, classes)
    printConfusion( confusion, classes )
    printMeasures( confusion )

#---------------------------------------------------------------

def buildConfusion(tabledata, tree, classes):
    
    confusion = {}
    
    for c1 in classes:
        confusion[c1] = {}
        for c2 in classes:
            confusion[c1][c2] = 0
    # Fill it with results
    for d in tabledata:
        correctclass = d.getclass()
        predclass    = tree(d)
        confusion[str(correctclass)][str(predclass)] += 1

    return confusion


class SimpleTreeLearnerSetProb():
    """
    Orange.classification.tree.SimpleTreeLearner which sets the skip_prob
    so that on average a square root of the attributes will be 
    randomly choosen for each split.
    """
    def __init__(self, wrapped):
        self.wrapped = wrapped

    def __call__(self, examples, weight=0):
        self.wrapped.skip_prob = 1-len(examples.domain.attributes)**0.5/len(examples.domain.attributes)
        return self.wrapped(examples)

#----------------------------------------------------------


def main():


    paper_table = build_papers_table()

    tree = Orange.classification.tree.TreeLearner(min_instances=5,
    measure="gainRatio", rand=random)
    rf_def = Orange.ensemble.forest.RandomForestLearner(trees=50,
    base_learner=tree, name="for_gain", rand=random)

    #random forests with simple trees - simple trees do random attribute selection by themselves
    st = Orange.classification.tree.SimpleTreeLearner(min_instances=5)
    stp = SimpleTreeLearnerSetProb(st)
    rf_simple = Orange.ensemble.forest.RandomForestLearner(learner=stp, trees=50, name="for_simp")

    learners = [ rf_def, rf_simple ]


    results = Orange.evaluation.testing.proportion_test([rf_def,rf_simple], paper_table, times=1)
    points = Orange.evaluation.scoring.compute_ROC(results)[0]

    xs = [ p[0] for p in points ]
    ys = [ p[1] for p in points ]

    plt.xlim(xmax=1)
    plt.ylabel("True Positives")
    plt.xlabel("False Positives")
    for x,y in [p for p in points]:
        plt.plot([0,1],[0,1],'k--')
        plt.plot(xs,ys,'b-')

    plt.savefig("ROC.png")

    print "--------------------3 Fold Cross Validation------------------------"

    results = Orange.evaluation.testing.cross_validation(learners, paper_table,
            folds=3, storeClassifiers=1,
            random_generator=Orange.misc.Random(int(random.random()*10)))


    import cPickle


    print "Learner  CA     Brier  AUC"
    for i in range(len(learners)):
        print "%-8s %5.3f  %5.3f  %5.3f" % (learners[i].name, \
        Orange.evaluation.scoring.CA(results)[i], 
        Orange.evaluation.scoring.Brier_score(results)[i],
        Orange.evaluation.scoring.AUC(results)[i])


        with open(("results_%d.pickle" % i), "wb") as f:
            cPickle.dump(results, f)


        for k in range(0,3):
            indices = [paper_table[x] for x in range(0,len(paper_table)) 
                if results.results[x].iteration_number == k]
            printResults(indices, results.classifiers[k][i], TYPE_DIRS.keys())

    print "Storing tree learned from data"


    tree = rf_simple( paper_table)

    with open("paper_types.model",'wb') as f:
        cPickle.dump(tree, f)

if __name__== "__main__":
    main()

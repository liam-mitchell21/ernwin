import unittest
import time

import scipy.interpolate as si
import scipy.stats as ss
import borgy.utilities.statistics as cus

from borgy.utilities.statistics import interpolated_kde
from scipy.stats import norm
from scipy.stats import gaussian_kde
import matplotlib.pylab as pl
import numpy as np
from numpy import log, allclose

class TestInterpolatedKde(unittest.TestCase):

    def test_estimate(self):
        
        samples = norm.rvs(size=100)
        bsamples = np.linspace(-4, 4)

        kde = gaussian_kde(samples)
        ik = interpolated_kde(samples, (min(bsamples), max(bsamples)))

        kdata = log(kde(samples))
        idata = ik(samples)

        self.assertTrue(allclose(kdata, idata))

        '''
        pl.hist(samples, normed=True)
        #pl.plot(samples, kde(samples), 'o')
        pl.plot(bsamples, kde(bsamples), 'o')

        pl.plot(bsamples, ik(bsamples))
        pl.plot(bsamples, norm.pdf(bsamples))

        pl.show()
        '''

def func(x, y):
    return x*(1-x)*np.cos(4*np.pi*x) * np.sin(4*np.pi*y**2)**2

class TestInterpolatedMultiKDE(unittest.TestCase):
    def test_estimate_orig(self):

        grid_x, grid_y = np.mgrid[0:1:50j, 0:1:100j]

        points = np.random.rand(100, 2)
        values = func(points[:,0], points[:,1])

        from scipy.interpolate import griddata
        grid_z0 = griddata(points, values, (grid_x, grid_y), method='nearest')
        grid_z1 = griddata(points, values, (grid_x, grid_y), method='linear')
        grid_z2 = griddata(points, values, (grid_x, grid_y), method='cubic')

        import matplotlib.pyplot as plt
        plt.subplot(121)

        print func(grid_x, grid_y)

        plt.imshow(func(grid_x, grid_y).T, extent=(0,1,0,1), origin='lower')
        plt.plot(points[:,0], points[:,1], 'k.', ms=1)
        plt.title('Original')
        plt.subplot(222)
        plt.imshow(grid_z0.T, extent=(0,1,0,1), origin='lower')
        plt.title('Nearest')
        plt.subplot(223)
        plt.imshow(grid_z1.T, extent=(0,1,0,1), origin='lower')
        plt.title('Linear')
        plt.subplot(224)
        plt.imshow(grid_z2.T, extent=(0,1,0,1), origin='lower')
        plt.title('Cubic')
        plt.gcf().set_size_inches(6, 6)
        #plt.show()

    def test_estimate(self):
        x, y = np.mgrid[0:1:10j, 0:1:10j]
        x1,y1 = np.mgrid[0:1:40j, 0:1:40j]

        g_points = np.append(x.reshape(-1,1), y.reshape(-1,1), axis=1)
        g_points1 = np.append(x1.reshape(-1,1), y1.reshape(-1,1), axis=1)

        points = np.random.rand(100, 2)
        kde = ss.gaussian_kde(points.T)

        values = kde(points.T)
        #print "points:", points
        #print "values:", values
        

        inter = si.LinearNDInterpolator(g_points, kde(g_points.T))
        interp = inter(g_points)

        self.assertTrue(np.allclose(kde(g_points.T), interp))

        import matplotlib.pyplot as plt

        plt.subplot(121)

        plt.imshow(kde(g_points.T).reshape(10,-1), extent=(0,1,0,1), origin='lower')
        plt.plot(points[:,0], points[:,1], 'k.', ms=1)
        plt.title('Original')

        plt.subplot(122)
        plt.imshow(inter(g_points1).reshape(40,-1), extent=(0,1,0,1), origin='lower')
        plt.title('Interpolation')
        
        #plt.show()

    def test_estimate_no_grid(self):
        x, y = np.mgrid[0:1:10j, 0:1:10j]
        x1,y1 = np.mgrid[0:1:20j, 0:1:20j]

        g_points = np.append(x.reshape(-1,1), y.reshape(-1,1), axis=1)
        g_points1 = np.append(x1.reshape(-1,1), y1.reshape(-1,1), axis=1)

        points = np.random.rand(10, 2)
        kde = ss.gaussian_kde(points.T)

        values = kde(points.T)
        #print "points:", points
        #print "values:", values
        

        inter = si.LinearNDInterpolator(points, kde(points.T))
        interp = inter(points)

        self.assertTrue(np.allclose(kde(points.T), interp))

        import matplotlib.pyplot as plt

        plt.subplot(121)

        plt.imshow(kde(g_points.T).reshape(10,-1), extent=(0,1,0,1), origin='lower')
        plt.plot(points[:,0], points[:,1], 'k.', ms=1)
        plt.title('Original')

        plt.subplot(122)
        plt.imshow(inter(g_points1).reshape(20,-1), extent=(0,1,0,1), origin='lower')
        plt.title('Interpolation')
        
        #plt.show()

    def test_estimate2(self):
        points = np.random.rand(10, 2)

        kde = ss.gaussian_kde(points.T)
        imk = cus.InterpolatedMultiKDE(points)

        for point in points:
            self.assertTrue(allclose(kde(point), imk(point)))
    
        points = np.random.rand(10, 3)

        kde = ss.gaussian_kde(points.T)
        imk = cus.InterpolatedMultiKDE(points)

        for point in points:
            self.assertTrue(allclose(kde(point), imk(point)))

    def time_imk(self):
        points = np.random.rand(1000, 3)
        points1 = np.random.rand(1000, 3)

        print "here:"
        kde = ss.gaussian_kde(points.T)
        print "here1:"
        imk = cus.InterpolatedMultiKDE(points)
        print "here2:"

        t = time.time()
        k = kde(points1.T)
        print "time kde:", time.time() - t

        t = time.time()
        i = imk(points1)
        print "time imk:", time.time() - t
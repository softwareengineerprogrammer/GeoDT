# -*- coding: utf-8 -*-
import iapws.iapws97

print('GeoDT_3.8.3')

# ****************************************************************************
# Calculate economic potential of EGS & optimize borehole layout with caging
# Author: Luke P. Frash
#
# Notation:
#  !!! for code needing to be updated (e.g, limitations or work in progress)
#  *** for breaks between key sections
# ****************************************************************************

# ****************************************************************************
#### libraries
# ****************************************************************************
import numpy as np
from scipy.linalg import solve
# from scipy.stats import lognorm
import pylab
import math
from iapws import IAPWS97 as therm
import SimpleGeometry as sg
from scipy import stats

# import sys
# import matplotlib.pyplot as plt
# import copy

# ****************************************************************************
#### unit conversions
# ****************************************************************************
# Unit conversions for convenience
lpm = (0.1 * 0.1 * 0.1) / (60.0)
ft = 12 * 25.4e-3  # m
m = (1.0 / ft)  # ft
deg = 1.0 * math.pi / 180.0
# rad=1.0/deg
gal = 3.785 * 0.1 * 0.1 * 0.1  # m^3=3.785 l
gpm = gal / 60.0
liter = 0.1 * 0.1 * 0.1
lps = liter / 1.0  # = liters per second
cP = 10.0 ** -3  # Pa-s
g = 9.81  # m/s2
MPa = 10.0 ** 6.0  # Pa
GPa = 10.0 ** 9.0  # Pa
darcy = 9.869233 * 10 ** -13  # m2
mD = darcy * 10.0 ** 3.0  # m2
yr = 365.2425 * 24.0 * 60.0 * 60.0  # s
mLmin = 1.66667e-8  # m3/s
um2cm = 1.0e-12  # m2
pi = math.pi


# ****************************************************************************
#### classes, functions, and modules
# ****************************************************************************

def HF(r, x0, strikeRad, dipRad, h=0.5):
    """
    Place a radial hydraulic fracture of radius r at x0
    """
    # start with a disk
    disk = sg.diskObj(r, h)
    disk = sg.rotateObj(disk, [0.0, 1.0, 0.0], dipRad)
    disk = sg.rotateObj(disk, [0.0, 0.0, 1.0], -strikeRad)
    disk = sg.transObj(disk, x0)
    return disk

def typ(key):
    """
    definitions and cross-referencing for pipe types
    """

    ret = []
    choices = np.asarray([
        ['boundary', '-3'],
        ['producer', '-2'],
        ['injector', '-1'],
        ['pipe', '0'],
        ['fracture', '1'],
        ['propped', '2'],
        ['darcy', '3'],
        ['choke', '4']
    ])
    key = str(key)
    ret = np.where(choices == key)
    if ret[1] == 0:
        ret = int(choices[ret[0], 1][0])
    elif ret[1] == 1:
        ret = str(choices[ret[0], 0][0])
    else:
        print('**invalid pipe type defined**')
        ret = []
    return ret


def azn_dip(x0, x1):
    """
    Returns
    -------
    azn and dip from endpoints
    """
    dx = x1[0] - x0[0]
    dy = x1[1] - x0[1]
    dz = x1[2] - x0[2]
    dr = (dx ** 2.0 + dy ** 2.0) ** 0.5
    azn = []
    dip = []
    if dx == 0 and dy >= 0:
        azn = 0.0
    elif dx == 0:
        azn = pi
    else:
        azn = np.sign(dx) * np.arccos(dy / dr) + (1 - np.sign(dx)) * pi
    if dr == 0.0:
        dip = -np.sign(dz) * pi / 2.0
    else:
        dip = -np.arctan(dz / dr)
    return azn, dip


def exponential_trunc(nsam,
                      bval=1.0,
                      Mmax=5.0,
                      Mwin=1.0,
                      prob=0.1):
    """
    random samples from a truncated exponential distribution
    """

    # zero-centered Mcap
    lamba = np.log(10) * bval
    Mcap = (-1.0 / lamba) * np.log(prob / (np.exp(lamba * Mwin) - 1.0 + prob))

    # calculated Mmin
    Mmin = Mmax - Mcap

    # sample sets with resamples out-of-range values
    s0 = np.random.exponential(1.0 / (np.log(10) * bval), nsam) + Mmin
    iters = 0
    while 1:
        iters += 1
        r_pl = s0 > Mmax
        if np.sum(r_pl) > 0:
            r_dr = np.random.exponential(1.0 / (np.log(10) * bval), nsam) + Mmin
            s0 = s0 * (1 - r_pl) + r_dr * (r_pl)
        else:
            break
        if iters > 100:
            break
    return s0


def contact_trunc(nsam,
                  weight=0.15,
                  bd_nom=0.002,
                  stddev=0.5 * 0.002,
                  exp_B=0.5,
                  exp_C=0.5 / np.pi,
                  bd_min=0.0001,
                  bd_max=3.0 * 0.002):
    """
    get random samples from a 'contact' distribution
    """

    # binomial samples
    n1 = np.random.binomial(nsam, weight, (1))
    n2 = nsam - n1

    # exponential samples
    s1 = np.random.exponential(exp_B, n1) * exp_C * bd_nom + bd_min
    iters = 0
    while 1:
        iters += 1
        r_pl = s1 > bd_max
        if np.sum(r_pl) > 0:
            r_dr = np.random.exponential(exp_B, n1) * exp_C * bd_nom + bd_min
            s1 = s1 * (1 - r_pl) + r_dr * (r_pl)
        else:
            break
        if iters > 100:
            break

    # normal samples
    s2 = np.random.normal(bd_nom, stddev, n2)
    iters = 0
    while 1:
        iters += 1
        r_pl = (s2 > bd_max) + (s2 < bd_min)
        if np.sum(r_pl) > 0:
            r_dr = np.random.normal(bd_nom, stddev, n2)
            s2 = s2 * (1 - r_pl) + r_dr * (r_pl)
        else:
            break
        if iters > 100:
            break
    s0 = np.concatenate((s1, s2), axis=0)
    return s0


def lognorm_trunc(nsam, logmu=0.0, logdev=1.0,
                  loglo=-2.0, loghi=2.0):
    """
    get random samples from a log normal distribution
    """

    # normal samples
    s0 = np.random.normal(logmu, logdev, nsam)
    iters = 0
    while 1:
        iters += 1
        r_pl = (s0 > loghi) + (s0 < loglo)
        if np.sum(r_pl) > 0:
            r_dr = np.random.normal(logmu, logdev, nsam)
            s0 = s0 * (1 - r_pl) + r_dr * (r_pl)
        else:
            break
        if iters > 100:
            break

    return 10.0 ** s0


def norm_trunc(nsam,
               mu=0.0,
               dev=1.0,
               lo=-2.0,
               hi=2.0):
    """
    get random samples from a log normal distribution
    """

    # normal samples
    s0 = np.random.normal(mu, dev, nsam)
    iters = 0
    while 1:
        iters += 1
        r_pl = (s0 > hi) + (s0 < lo)
        if np.sum(r_pl) > 0:
            r_dr = np.random.normal(mu, dev, nsam)
            s0 = s0 * (1 - r_pl) + r_dr * (r_pl)
        else:
            break
        if iters > 100:
            break
    return s0


class Cauchy:
    """
    functions modified from JPM
    """

    def __init__(self):
        self.sigP = np.zeros((3, 3), dtype=float)
        self.sigG = np.zeros((3, 3), dtype=float)
        self.Sh = 0.0  # Pa
        self.SH = 0.0  # Pa
        self.SV = 0.0  # Pa
        self.Sh_azn = 0.0 * deg  # rad
        self.Sh_dip = 0.0 * deg  # rad

    def rotationMatrix(self, axis, theta):
        """
        http://stackoverflow.com/questions/6802577/python-rotation-of-3d-vector
        """
        # return the rotation matrix associated with counterclockwise rotation about the given axis by theta radians.
        axis = np.asarray(axis)
        axis = axis / math.sqrt(np.dot(axis, axis))
        a = math.cos(theta / 2.0)
        b, c, d = -axis * math.sin(theta / 2.0)
        aa, bb, cc, dd = a * a, b * b, c * c, d * d
        bc, ad, ac, ab, bd, cd = b * c, a * d, a * c, a * b, b * d, c * d
        return np.array([[aa + bb - cc - dd, 2 * (bc + ad), 2 * (bd - ac)],
                         [2 * (bc - ad), aa + cc - bb - dd, 2 * (cd + ab)],
                         [2 * (bd + ac), 2 * (cd - ab), aa + dd - bb - cc]])

    def rotateTensor(self, tensor, axis, theta):
        """
        http://www.continuummechanics.org/stressxforms.html
        """
        rot = self.rotationMatrix(axis, theta)
        return np.dot(rot, np.dot(tensor, np.transpose(rot)))

    def normal_from_dip(self, dip_direction, dip_angle):
        """
        Projection of normal plane from dip directions
        """
        # dip_direction=0 is north -> nrmxH=0, nrmyH=1
        # dip_direction=90 is east -> nrmxH=1, nrmyH=0
        nrmxH = np.sin(dip_direction)
        nrmyH = np.cos(dip_direction)
        # The lateral components of the normals are corrected for the dip angle
        nrmx = nrmxH * np.sin(dip_angle)
        nrmy = nrmyH * np.sin(dip_angle)
        # The vertical
        nrmz = np.cos(dip_angle)
        return np.asarray([nrmx, nrmy, nrmz])

    def Pc(self, nrmP, phi, mcc):
        """
        normal stress and critical slip or opening pressure
        """
        # Shear traction on the fault segment
        t = np.zeros([3])
        for i in range(3):
            for j in range(3):
                t[i] += self.sigG[j][i] * nrmP[j]
        # Normal component of the traction
        Sn = 0.0
        for i in range(3):
            Sn += t[i] * nrmP[i]
        # Shear component of the traction
        tauV = np.zeros([3])
        for i in range(3):
            tauV[i] = t[i] - Sn * nrmP[i]
        tau = np.sqrt(tauV[0] * tauV[0] + tauV[1] * tauV[1] + tauV[2] * tauV[2])
        # Critical pressure for slip from mohr-coulomb
        Pc1 = Sn - (tau - mcc) / np.tan(phi)
        # Critical pressure for tensile opening
        Pc2 = Sn + mcc
        # Critical pressure for fracture activation
        Pc = np.min([Pc1, Pc2])
        return Pc, Sn, tau

    def Pc_frac(self, strike, dip, phi, mcc):
        """
        critical slip given fracture strike and dip
        """
        # get fracture normal vector
        nrmG = self.normal_from_dip(strike + np.pi / 2, dip)
        return self.Pc(nrmG, phi, mcc)

    def set_sigG_from_Principal(self, Sh, SH, SV, ShAzn, ShDip):
        """
        Set cauchy stress tensor from rotated principal stresses
        """
        # Stresses in the principal stress directions
        # We have been given the azimuth of the minimum stress, ShAzimuthDeg, to compare with 90 (x-dir)
        # That is Sh==Sxx, SH=Syy, SV=Szz in the principal stress coord system
        sigP = np.asarray([
            [Sh, 0.0, 0.0],
            [0.0, SH, 0.0],
            [0.0, 0.0, SV]
        ])
        # Rotate about z-axis
        deltaShAz = ShAzn - np.pi / 2.0  # (ShAznDeg-90.0)*np.pi/180.0
        # Rotate about y-axis
        ShDip = -ShDip  # -ShDipDeg*np.pi/180.0
        sigG = self.rotateTensor(sigP, [0.0, 1.0, 0.0], -ShDip)
        sigG = self.rotateTensor(sigG, [0.0, 0.0, 1.0], -deltaShAz)
        self.sigP = sigP
        self.sigG = sigG
        self.Sh = Sh  # Pa
        self.SH = SH  # Pa
        self.SV = SV  # Pa
        self.Sh_azn = ShAzn  # Deg*deg #rad
        self.Sh_dip = ShDip  # Deg*deg #rad
        return sigG

    def plot_Pc(self, phi, mcc, filename='Pc_stereoplot.png'):
        """
        Plot critical pressure
        """

        # Working variables
        nRad = 100
        dip_angle_deg = np.asarray(range(nRad + 1)) * (90.0 / nRad)
        nTheta = 200
        dip_dir_radians = np.asarray(range(nTheta + 1)) * (2.0 * np.pi / nTheta)
        png_dpi = 128
        # Calculate critical dP
        criticalDelPpG = np.zeros([nRad, nTheta])
        for i in range(nRad):
            for j in range(nTheta):
                # Convert the x and y into a normal to the fracture using dip angle and dip direction
                nrmG = self.normal_from_dip(dip_dir_radians[j], dip_angle_deg[i] * deg)
                nrmx, nrmy, nrmz = nrmG[0], nrmG[1], nrmG[2]
                criticalDelPpG[i, j], h1, h2 = self.Pc(np.asarray([nrmx, nrmy, nrmz]), phi, mcc)
        # Plot critical slip pressure (lower hemisphere projection)
        fig = pylab.figure(figsize=(6, 4.75), dpi=png_dpi, tight_layout=True, facecolor='w', edgecolor='k')
        ax = fig.add_subplot(111, projection='polar')
        ax.set_theta_zero_location("N")
        ax.set_theta_direction(-1)
        pylab.pcolormesh(dip_dir_radians + np.pi, dip_angle_deg,
                         np.ma.masked_where(np.isnan(criticalDelPpG), criticalDelPpG), vmin=110.0 * MPa,
                         vmax=150.0 * MPa, cmap='rainbow_r')  # vmin=0.0*MPa, vmax=self.SH,cmap='rainbow_r')
        ax.grid(True)
        ax.set_rgrids([0, 30, 60, 90], labels=[])
        ax.set_thetagrids([0, 90, 180, 270])
        pylab.colorbar()
        ax.set_title("Critical pressure for Mohr-Coulomb failure", va='bottom')
        pylab.savefig(filename, format='png', dpi=png_dpi)
        pylab.close()


class Reservoir:
    """
    reservoir object
    """

    def __init__(self):
        # rock properties
        self.size = 800.0  # m
        self.ResDepth = 6000.0  # m
        self.ResGradient = 50.0  # 56.70 # C/km; average = 25 C/km
        self.ResRho = 2700.0  # kg/m3
        self.ResKt = 2.5  # W/m-K
        self.ResSv = 2063.0  # kJ/m3-K
        self.AmbTempC = 25.0  # C
        self.AmbPres = 0.101 * MPa  # Example: 0.01 MPa #Atmospheric: 0.101 # MPa
        self.ResE = 50.0 * GPa
        self.Resv = 0.3
        self.ResG = self.ResE / (2.0 * (1.0 + self.Resv))
        self.Ks3 = 0.5
        self.Ks2 = 0.75  # 0.75
        self.s3Azn = 0.0 * deg
        self.s3AznVar = 0.0 * deg
        self.s3Dip = 0.0 * deg
        self.s3DipVar = 0.0 * deg

        # fracture orientation parameters #[i,:] set, [0,0:2] min, max --or-- nom, std
        self.fNum = np.asarray([10,
                                10,
                                10], dtype=int)  # count
        """
        number of fractures in each set
        """

        self.fDia = np.asarray([[300.0, 900.0],
                                [300.0, 900.0],
                                [300.0, 900.0]], dtype=float)  # m
        self.fStr = np.asarray([[79.0 * deg, 8.0 * deg],
                                [0.0 * deg, 8.0 * deg],
                                [180.0 * deg, 8.0 * deg]], dtype=float)  # m
        self.fDip = np.asarray([[60.0 * deg, 8.0 * deg],
                                [90.0 * deg, 8.0 * deg],
                                [0.0 * deg, 8.0 * deg]], dtype=float)  # m

        # fracture hydraulic parameters
        self.gamma = np.asarray([10.0 ** -3.0, 10.0 ** -2.0, 10.0 ** -1.2])
        self.n1 = np.asarray([1.0, 1.0, 1.0])
        self.a = np.asarray([0.000, 0.200, 0.800])
        self.b = np.asarray([0.999, 1.0, 1.001])
        self.N = np.asarray([0.0, 0.6, 2.0])
        self.alpha = np.asarray([2.0e-9, 2.9e-8, 10.0e-8])
        self.prop_alpha = np.asarray([2.0e-9, 2.9e-8, 10.0e-8])
        self.bh = np.asarray([0.00005, 0.0001, 0.0002])  # np.asarray([0.00005,0.00010,0.00020])
        self.bh_min = 0.00005  # m
        self.bh_max = 0.02  # 0.02000 #m
        self.bh_bound = 0.003
        self.f_roughness = np.asarray([0.80, 0.90, 1.00])

        # well parameters
        self.w_count = 3  # wells
        self.w_spacing = 200.0  # m
        self.w_length = 800.0  # m
        self.w_azimuth = self.s3Azn + 0.0 * deg  # rad
        self.w_dip = self.s3Dip + 0.0 * deg  # rad
        self.w_proportion = 0.8  # m/m
        self.w_phase = -45.0 * deg  # rad
        self.w_toe = 0.0 * deg  # rad
        self.w_skew = 15.0 * deg  # rad
        self.w_intervals = 5  # breaks in well length
        self.ra = 0.0254 * 3.0  # 0.0254*3.0 #m
        self.rb = self.ra + 0.0254 * 0.5  # m
        self.rc = self.ra + 0.0254 * 1.0  # m
        self.rgh = 80.0

        # cement properties
        self.CemKt = 2.0  # W/m-K
        self.CemSv = 2000.0  # kJ/m3-K

        # thermal-electric power parameters
        self.GenEfficiency = 0.85  # kWe/kWt
        # self.InjPres = 1.0 #Example: 0.135 #Model: 2.0 # MPa
        # self.TargetPower = 1000 #Example: 2964 # kWe
        self.LifeSpan = 20.5 * yr  # years
        self.TimeSteps = 41  # steps
        self.p_whp = 1.0 * MPa  # Pa
        self.Tinj = 95.0  # C
        self.H_ConvCoef = 3.0  # kW/m2-K
        self.dT0 = 10.0  # K
        self.dE0 = 500.0  # kJ/m2

        # water base parameters
        self.PoreRho = 980.0  # kg/m3 starting guess
        self.Poremu = 0.9 * cP  # Pa-s
        self.Porek = 0.1 * mD  # m2
        self.kf = 300.0 * um2cm  # m2

        # calculated parameters
        self.BH_T = self.ResDepth * 10 ** -3.0 * self.ResGradient + self.AmbTempC + 273.15  # K
        self.BH_P = self.PoreRho * g * self.ResDepth + self.AmbPres  # Pa
        self.s1 = self.ResRho * g * self.ResDepth  # Pa
        self.s2 = self.Ks2 * (self.s1 - self.BH_P) + self.BH_P  # Pa
        self.s3 = self.Ks3 * (self.s1 - self.BH_P) + self.BH_P  # Pa

        # cauchy stress
        self.stress = Cauchy()
        self.stress.set_sigG_from_Principal(self.s3, self.s2, self.s1, self.s3Azn, self.s3Dip)
        # self.stress.plot_Pc(30.0*deg,5.0*MPa)

        # stimulation parameters
        self.perf = 1
        self.r_perf = 50.0  # m

        self.sand = 0.3
        """sand ratio in frac fluid by volume"""

        self.leakoff = 0.0
        """Carter leakoff"""

        self.dPp = -2.0 * MPa
        """production well pressure drawdown"""

        self.dPi = 0.5 * MPa
        self.stim_limit = 5
        self.Qinj = 0.01  # m3/s
        self.Vinj = self.Qinj * self.LifeSpan
        self.Qstim = 0.04  # m3/s
        self.Vstim = 50000.0  # m3
        self.pfinal_max = 999.9 * MPa  # Pa, maximum long term injection pressure

        self.bval = 1.0
        """Gutenberg-Richter magnitude scaling"""

        self.phi = np.asarray([20.0 * deg, 35.0 * deg, 50.0 * deg])  # rad
        self.mcc = np.asarray([5.0 * MPa, 10.0 * MPa, 15.0 * MPa])  # Pa
        self.hfmcc = 0.1 * MPa
        self.hfphi = 30.0 * deg
        self.Kic = 1.5 * MPa  # Pa-m**0.5

    def re_init(self):
        # calculated parameters
        self.ResG = self.ResE / (2.0 * (1.0 + self.Resv))
        self.BH_T = self.ResDepth * 10 ** -3.0 * self.ResGradient + self.AmbTempC + 273.15  # K
        self.BH_P = self.PoreRho * g * self.ResDepth + self.AmbPres  # Pa
        self.s1 = self.ResRho * g * self.ResDepth  # Pa
        self.s2 = self.Ks2 * (self.s1 - self.BH_P) + self.BH_P  # Pa
        self.s3 = self.Ks3 * (self.s1 - self.BH_P) + self.BH_P  # Pa
        self.stress.set_sigG_from_Principal(self.s3, self.s2, self.s1, self.s3Azn, self.s3Dip)
        self.Vinj = self.Qinj * self.LifeSpan
        # self.rb = self.ra + 0.0254*0.5 # m
        # self.rc = self.ra + 0.0254*1.0 # m


class Surface:
    """
    surface object
    """

    def __init__(self, x0=0.0, y0=0.0, z0=0.0, dia=1.0, stk=0.0 * deg, dip=90.0 * deg,
                 ty='fracture', rock=Reservoir(),
                 mcc=-1, phi=-1):
        # *** base parameters ***

        # node number of center point
        self.ci = -1

        # geometry
        self.c0 = np.asarray([x0, y0, z0])
        self.dia = dia
        self.str = stk
        self.dip = dip
        self.typ = typ(ty)

        # shear strength
        self.phi = -1.0  # rad
        self.mcc = -1.0  # Pa

        # stress state
        self.sn = 5.0 * MPa
        self.En = 50.0 * GPa
        self.vn = 0.30
        self.Pc = 0.0 * MPa
        self.tau = 0.0 * MPa

        # stimulation information
        self.stim = 0
        self.Pmax = 0.0 * MPa
        self.Pcen = 0.0 * MPa
        self.Mws = [-99.9]  # maximum magnitude seismic event tracker
        self.arup = 1.0  # rupture area available for seismicity
        self.hydroprop = False
        self.prop_load = 0.0  # m3 #absolute proppant volume
        self.prop_alpha = norm_trunc(1, rock.prop_alpha[1], rock.prop_alpha[1], rock.prop_alpha[0], rock.prop_alpha[2])[
            0]  # proppant compressibility modulus
        self.roughness = rock.f_roughness if type(rock.f_roughness) is float else \
            np.random.uniform(rock.f_roughness[0], rock.f_roughness[2], (1))[0]  # open flow roughness
        self.kf = rock.kf  # proppant pack permeability

        # scaling
        self.u_N = -1.0
        self.u_alpha = -1.0
        self.u_a = -1.0
        self.u_b = -1.0
        self.u_gamma = -1.0
        self.u_n1 = -1.0
        # hydraulic geometry
        self.bh = -1.0

        # *** stochastic sampled parameters *** #!!!
        self.u_gamma = \
            lognorm_trunc(1, np.log10(rock.gamma[1]), 0.45, np.log10(rock.gamma[0]), np.log10(rock.gamma[2]))[0]
        self.u_n1 = np.random.uniform(rock.n1[0], rock.n1[2], (1))[0]
        self.u_a = norm_trunc(1, rock.a[1], 0.150, rock.a[0], rock.a[2])[0]
        self.u_b = np.random.uniform(rock.b[0], rock.b[2], (1))[0]
        self.u_N = \
            contact_trunc(1, 0.15, rock.N[1], 0.5 * rock.N[1], 0.5, 0.5 * rock.N[1] / np.pi, rock.N[0], rock.N[2])[0]
        self.u_alpha = norm_trunc(1, rock.alpha[1], rock.alpha[1], rock.alpha[0], rock.alpha[2])[0]
        self.bh = norm_trunc(1, rock.bh[1], rock.bh[1], rock.bh[0], rock.bh[2])[
            0]  # !!! would be nice to replace this with a physics based estimate
        if phi < 0:
            self.phi = np.random.uniform(rock.phi[0], rock.phi[2], (1))[0]
        else:
            self.phi = phi
        if mcc < 0:
            self.mcc = np.random.uniform(rock.mcc[0], rock.mcc[2], (1))[0]
        else:
            self.mcc = mcc

        # stress state
        self.Pc, self.sn, self.tau = rock.stress.Pc_frac(self.str, self.dip, self.phi, self.mcc)

        # apertures
        self.bd = self.bh / self.u_N
        self.bd0 = self.bd
        self.bd0p = 0.0
        self.vol = (4.0 / 3.0) * pi * 0.25 * self.dia ** 2.0 * 0.5 * self.bd
        self.arup = 0.25 * np.pi * self.dia ** 2.0

    def check_integrity(self, rock=Reservoir(), pres=0.0):
        """
        adjust fracture cohesion to prevent runaway stimulation at specified conditions
        """
        # originally assigned values
        Pc0 = self.Pc
        mcc0 = self.mcc
        phi0 = self.phi

        # shear stability limit
        mcc_c = self.tau - (self.sn - pres) * np.tan(self.phi)

        # tensile stability limit
        mcc_t = pres - self.sn

        # update fracture cohesion to ensure stability at the input conditions
        self.mcc = np.max([self.mcc, mcc_c, mcc_t])

        # recompute critical conditions
        self.Pc, self.sn, self.tau = rock.stress.Pc_frac(self.str, self.dip, self.phi, self.mcc)

        # output message
        if self.Pc > Pc0:
            print(
                'alert: critical fracture at Tau = %.2e, sn = %.2e, and Pp %.2e having phi = %.2e rad, mcc = %.2e Pa, Pc = %.2e Pa adjusted to phi = %.2e rad, mcc = %.2e Pa, Pc = %.2e Pa'
                % (self.tau, self.sn, pres, phi0, mcc0, Pc0, self.phi, self.mcc, self.Pc))

    def make_critical(self, rock=Reservoir(), pres=0.0):
        """
        set fracture cohesion to critical value at specified conditions
        """
        # shear stability limit
        mcc_c = self.tau - (self.sn - pres) * np.tan(self.phi)

        # tensile stability limit
        mcc_t = pres - self.sn

        # update fracture cohesion to enforce critical stability at the input conditions
        self.mcc = np.max([mcc_c, mcc_t])

        # recompute critical conditions
        self.Pc, self.sn, self.tau = rock.stress.Pc_frac(self.str, self.dip, self.phi, self.mcc)

        # output message
        print('         hydrofrac critical cohesion calculated as %.2e Pa to obtain Pc = %.2e Pa' % (self.mcc, self.Pc))
        # error case
        if self.Pc <= self.sn:
            print('         *** error: solution gives closed supercritical shear instead of hydrofracture')

    def check_integrity_old(self, rock=Reservoir(), pres=0.0):
        """
        adjust frictional properties to prevent runaway stimulation at specified conditions
        (attempts to get more reasonable friction angle or more reasonable cohesion... but doesn't work well)
        """
        # tensile stability
        mcc_t = pres - self.sn

        # low shear stress stability
        mcc_s = self.tau - (self.sn - pres) * np.tan(self.phi)

        # high shear stress stability
        phi_s = np.arctan((self.tau - self.mcc) / (self.sn - pres))

        # shear failure critical angle
        if (pres < self.sn) and (self.mcc < self.tau):
            mcc_crit = 0.0
            phi_crit = phi_s
        # tensile failure critical cohesion
        else:
            mcc_crit = np.max([mcc_t, mcc_s])
            phi_crit = 0.0

        # update fracture properties to attain stability at the input conditions
        Pc0 = self.Pc
        mcc0 = self.mcc
        phi0 = self.phi
        self.phi = np.max([self.phi, phi_crit])
        self.mcc = np.max([self.mcc, mcc_crit])

        # recompute critical conditions
        self.Pc, self.sn, self.tau = rock.stress.Pc_frac(self.str, self.dip, self.phi, self.mcc)

        # output message
        if self.Pc > Pc0:
            print(
                'alert: critical fracture at Tau = %.2e, sn = %.2e, and Pp %.2e having mcc = %.2e Pa, phi = %.2e rad, Pc = %.2e Pa adjusted to phi = %.2e rad, mcc = %.2e Pa, Pc = %.2e Pa'
                % (self.tau, self.sn, pres, mcc0, phi0, Pc0, self.phi, self.mcc, self.Pc))

        # if (pres >= self.sn):
        #     phi_crit = 0.0 #use originally-specified phi
        #     mcc_crit = pres - self.sn + 1000.0 #1 kPa added to prevent numerical instabilities
        # #low stress fractures cause calculated critical friction angles to be excessive so mcc must be modified instead
        # elif (self.tau <= self.mcc):
        #     phi_crit = 0.0 #use originally-specified phi
        #     mcc_crit = self.tau - (self.sn - pres)*np.tan(self.phi)
        # #high shear & high stress fractures are stable as a function of phi, but low phi can cause runaway stimulation
        # else:
        #     pass
        # phi_crit = np.arctan((self.tau-self.mcc+0.5*rock.dPi)/(self.sn-pres))
        # if self.phi < phi_crit:
        #     self.phi = phi_crit
        #     self.mcc = mcc_crit
        #     self.Pc, self.sn, self.tau = rock.stress.Pc_frac(self.str, self.dip, self.phi, self.mcc)
        #     print('alert: a fracture was critically weak and adjusted to phi = %.2f' %(phi_crit))
        #     print('-- new Pc = %.3e Pa' %(self.Pc))


class Line:
    """
    line objects
    """

    def __init__(self,
                 x0=0.0,
                 y0=0.0,
                 z0=0.0,
                 length=1.0,
                 azn=0.0 * deg,
                 dip=0.0 * deg,
                 w_type='pipe',
                 ra=0.0254 * 3.0,
                 rb=0.0254 * 3.5,
                 rc=0.0254 * 3.5,
                 rough=80.0):
        # position geometry
        self.c0 = np.asarray([x0, y0, z0])  # origin
        self.leg = length  # length
        self.azn = azn  # axis azimuth north
        self.dip = dip  # axis dip from horizontal
        self.typ = typ(w_type)  # type of well

        # flow geometry
        self.ra = ra  # m
        self.rb = rb  # m
        self.rc = rc  # m
        self.rgh = rough

        # stimulation traits
        self.hydrofrac = False  # was well already hydrofraced?
        self.completed = False  # was well stimulation process completed?
        self.stabilize = False  # was well flow stabilized?


class Nodes:
    """
    node list object
    """

    def __init__(self):
        """
        initialization
        """
        self.r0 = np.asarray([np.inf, np.inf, np.inf])
        self.all = np.asarray([self.r0])
        self.tol = 0.0005
        self.num = len(self.all)
        self.p = np.zeros(self.num, dtype=float)
        self.T = np.zeros(self.num, dtype=float)
        self.h = np.zeros(self.num, dtype=float)

        # self.f_id = [[-1]]

    def add(self, c=np.asarray([0.0, 0.0, 0.0])):  # ,f_id=-1):
        """
        add a node
        """
        # round to within tolerance
        if not (np.isinf(c[0])):
            c = np.rint(c / self.tol) * self.tol
        # check for duplicate existing node
        ck_1 = np.asarray([np.isin(self.all[:, 0], c[0]), np.isin(self.all[:, 1], c[1]), np.isin(self.all[:, 2], c[2])])
        ck_2 = ck_1[0, :] * ck_1[1, :] * ck_1[2, :]
        ck_i = np.where(ck_2 == 1)
        # yes duplicate -> return index of existing node
        if len(ck_i[0]) > 0:
            #            if f_id != -1:
            #                self.f_id[ck_i[0][0]] += [f_id]
            return False, ck_i[0][0]
        # no duplicate -> add node -> return index of new node
        else:
            self.all = np.concatenate((self.all, np.asarray([c])), axis=0)
            self.num = len(self.all)
            self.p = np.concatenate((self.p, np.asarray([0.0])), axis=0)
            self.T = np.concatenate((self.T, np.asarray([0.0])), axis=0)
            self.h = np.concatenate((self.h, np.asarray([0.0])), axis=0)
            #            self.f_id += [[f_id]]
            return True, len(self.all) - 1


class Pipes:
    """
    pipe list object
    """

    def __init__(self):
        # initialization
        self.num = 0
        self.n0 = []  # source node
        self.n1 = []  # target node
        self.L = []  # length
        self.W = []  # width
        self.typ = []  # property source type
        self.fID = []  # property source index
        self.K = []  # flow solver coefficient
        self.n = []  # flow solver exponent
        self.Dh = []  # hydraulic aperture/diameter
        self.Dh_max = []  # hydraulic aperture/diameter limit
        self.frict = []  # hydraulic roughness
        self.hydrofraced = False  # tracker for fracture initiation

    # add a pipe
    def add(self, n0, n1, length, width, featTyp, featID, Dh=1.0, Dh_max=1.0, frict=1.0):
        self.n0 += [n0]
        self.n1 += [n1]
        self.L += [length]
        self.W += [width]
        self.typ += [featTyp]
        self.fID += [featID]
        self.K += [1.0]
        self.n += [1.0]
        self.num = len(self.n0)
        self.Dh += [Dh]
        self.Dh_max += [Dh_max]
        self.frict += [frict]
        self.hydrofraced = False

    def Dh_limit(self, Q, dP, rho=980.0, g=9.81, mu=0.9 * cP, k=0.1 * mD):
        """
        set hydraulic aperture limits based on minimum pressure drop at target flow rate
        """
        for i in range(0, self.num):
            if (int(self.typ[i]) in [typ('injector'), typ('producer'), typ('pipe')]):
                # a_max = (10.7e-5*self.L[i]*rho*g*Q/(dP*self.frict[i]**1.852))**(1.0/4.87) #oldest
                # a_max = (10.7e-4*self.L[i]*rho*g*Q/(dP*self.frict[i]**1.852))**(1.0/4.87) #old 2/11/23
                Lscaled = self.L[i] * mu / (0.9 * cP)
                a_max = (10.7e-4 * Lscaled * rho * g * Q / (dP * self.frict[i] ** 1.852)) ** (1.0 / 4.87)
                self.Dh_max[i] = a_max
            elif (int(self.typ[i]) in [typ('boundary'), typ('fracture'), typ('propped'), typ('choke')]):
                # bh_max = (12.0e-5*mu*Q*self.L[i]/(dP*self.W[i]))**(1.0/3.0)
                bh_max = (12.0e-4 * mu * Q * self.L[i] / (dP * self.W[i])) ** (1.0 / 3.0)
                self.Dh_max[i] = bh_max
            elif (int(self.typ[i]) in [typ('darcy')]):
                # t_max = 1.0e-5*Q*mu*self.L[i]/(k*self.W[i]*dP)
                t_max = 1.0e-4 * Q * mu * self.L[i] / (k * self.W[i] * dP)
                self.Dh_max[i] = t_max
            else:
                print('error: undefined type of conduit')
                exit()


class Mesh:
    """
    model object, functions, and data as object
    """

    def __init__(self):  # ,node=[],pipe=[],fracs=[],wells=[],hydfs=[],bound=[],geo3D=[]): #@@@ are these still used?
        # domain information
        self.rock = Reservoir()
        self.nodes = Nodes()
        self.pipes = Pipes()
        self.fracs = []
        self.wells = []
        self.hydfs = []
        self.bound = []
        self.faces = []

        # intersections tracker
        self.trakr = []  # index of fractures in chain

        # flow solver
        self.H = []  # boundary pressure head array, m
        self.Q = []  # boundary flow rate array, m3/s
        self.q = []  # calculated pipe flow rates
        self.v5 = []  # calculated inlet specific volume, m3/kg
        self.i_p = []  # constant flow well pressures, Pa
        self.i_q = []  # constant flow well rates, m3/s
        self.p_p = []  # constant pressure well pressures, Pa
        self.p_q = []  # constant pressure well rates, m3/s
        self.b_p = []  # boundary pressure, Pa
        self.b_q = []  # boundary rates, m3/s

        # heat solver
        self.Tb = []  # boundary temperatures
        self.R0 = []  # thermal radius
        self.Rt = []  # thermal radius over time
        self.ms = []  # pipe mass flow rates
        self.Et = []  # energy in rock over time
        self.Qt = []  # heat flow from rock over time
        self.Tt = []  # heat flow from rock over time
        self.ht = []  # enthalpy over time
        self.ts = []  # time stamps
        self.w_h = []  # wellhead enthalpy
        self.w_m = []  # wellhead mass flow
        self.p_E = []  # production energy
        self.b_h = []  # boundary enthalpy
        self.b_m = []  # boundary mass flow
        self.b_E = []  # boundary energy
        self.i_E = []  # injection energy
        self.i_mm = []  # mixed injection mass flow rate
        self.p_mm = []  # mixed produced mass flow rate
        self.p_hm = []  # mixed produced enthalpy

        # power solver
        self.Fout = []  # flash rankine power out
        self.Bout = []  # binary isobutane power out
        self.Qout = []  # pumping power out
        self.Pout = []  # net power out
        self.dhout = []  # heat extraction

        # validation stuff
        self.v_Rs = []
        self.v_ts = []
        self.v_Ps = []
        self.v_ws = []
        self.v_Vs = []
        self.v_Pn = []
        # economics
        self.NPV = 0.0

    #    # Static per-fracture hydraulic resistance terms using method of Luke P. Frash; [lower,nominal,upper]
    #    # .... also calculates the stress states on the fractutres
    #    def static_KQn(self,
    #             rnd_N = [0.01,0.2,0.2],
    #             rnd_alpha = [-0.002/MPa,-0.028/MPa,-0.080/MPa],
    #             rnd_a = [0.01,0.05,0.20],
    #             rnd_b = [0.7,0.8,0.9],
    #             rnd_gamma = [0.001,0.01,0.03]):
    #        #size
    #        num = len(self.faces)
    #        #exponential for N, alpha, gamma, and a
    #        r = np.random.exponential(scale=0.25,size=num)
    #        r[r>1.0] = 1.0
    #        r[r<0] = 0.0
    #        N = r*(rnd_N[2]-rnd_N[0])+rnd_N[0]
    #        r = np.random.exponential(scale=0.25,size=num)
    #        r[r>1.0] = 1.0
    #        r[r<0] = 0.0
    #        alpha = r*(rnd_alpha[2]-rnd_alpha[0])+rnd_alpha[0]
    #        r = np.random.exponential(scale=0.25,size=num)
    #        r[r>1.0] = 1.0
    #        r[r<0] = 0.0
    #        a = r*(rnd_a[2]-rnd_a[0])+rnd_a[0]
    #        r = np.random.exponential(scale=0.25,size=num)
    #        r[r>1.0] = 1.0
    #        r[r<0] = 0.0
    #        gamma = r*(rnd_gamma[2]-rnd_gamma[0])+rnd_gamma[0]
    #        #uniform for b
    #        b = np.random.uniform(rnd_b[0],rnd_b[2],size=num)
    #        #store properties
    #        for n in range(0,num):
    #            #aperture scaling parameters
    #            self.faces[n].u_N = N[n]
    #            self.faces[n].u_alpha = alpha[n]
    #            self.faces[n].u_a = a[n]
    #            self.faces[n].u_b = b[n]
    #            self.faces[n].u_gamma = gamma[n]
    #            #stress states
    #            self.faces[n].Pc, self.faces[n].sn, self.faces[n].tau = self.rock.stress.Pc_frac(self.faces[n].str, self.faces[n].dip, self.faces[n].phi, self.faces[n].mcc)

    def hydromech(self, f_id, fix=False):  # , pp=-666.0):
        """
        Propped fracture property estimation with geomechanics
        """
        # initialize stim
        stim = False

        # check if fracture will be stimulated
        if (self.faces[f_id].Pmax >= self.faces[f_id].Pc):
            self.faces[f_id].stim += 1
            stim = True
            print('-> fracture stimulated: %i' % (f_id))

        # pressures for analysis
        e_max = self.faces[f_id].sn - self.faces[f_id].Pmax

        # original bd0
        bd0 = self.faces[f_id].bd0

        # stimulation enabled
        if stim and not (fix):
            # *** shear ***
            # don't let shear be zero
            if self.faces[f_id].tau < 1.0:
                self.faces[f_id].tau = 1.0
            # maximum moment (shear stress method)
            M0max = self.faces[f_id].tau * self.faces[f_id].arup ** (3.0 / 2.0)
            Mwmax = (np.log10(M0max) - 9.1) / 1.5
            # mw sample from G-R
            mw = exponential_trunc(1, bval=self.rock.bval, Mmax=Mwmax, Mwin=1.0, prob=0.1)[0]
            # convert to moment magnitude (Mo)
            mo = 10.0 ** (mw * 1.5 + 9.1)
            # rupture length
            Lr = (4 * ((mo / self.faces[f_id].tau) ** (2 / 3)) / np.pi) ** 0.5
            # intermediate variables
            ds = mo / ((0.25 * np.pi * Lr ** 2.0) * self.rock.ResG)
            d0 = 0.5 * self.faces[f_id].u_gamma * (self.faces[f_id].dia ** self.faces[f_id].u_n1)
            bd0 = self.faces[f_id].u_a * (d0 ** self.faces[f_id].u_b)
            d1 = d0 + ds
            bd1 = self.faces[f_id].u_a * (d1 ** self.faces[f_id].u_b)
            dbd = bd1 - bd0
            # record stimulation magnitude and correct for seismic overestimation
            self.faces[f_id].Mws += [mw]
            # add to zero-stress dilatant aperture
            bd0 = self.faces[f_id].bd0 + dbd
            # override rupture length in tensile fractures to avoid overpredicting tensile seismicity
            if (e_max < 0.0):
                Lr = self.faces[f_id].dia

            # *** growth ***
            # grow fracture by larger of 20% fracture size or 5% domain size
            add_dia = np.max([0.2 * self.faces[f_id].dia, 0.05 * self.rock.size])
            # deduct event's rupture area from residual rupture area
            self.faces[f_id].arup = np.max([self.faces[f_id].arup - 0.25 * np.pi * Lr ** 2.0, 0.1])
            # update rupture area
            self.faces[f_id].arup = self.faces[f_id].arup + 0.25 * np.pi * (
                    (self.faces[f_id].dia + add_dia) ** 2.0 - self.faces[f_id].dia ** 2.0)
            # update fracture size
            self.faces[f_id].dia += add_dia

        # fracture parameters
        f_radius = 0.5 * self.faces[f_id].dia
        # propped closure with ideal loose spherical packing (Allen, 1985; Frings et al., 2011)
        prop_load = np.max([0.0, self.faces[f_id].prop_load])
        bd0p = (prop_load / 0.64) / (0.25 * np.pi * self.faces[f_id].dia ** 2.0)
        # closure pressure onto a proppant pack
        e_crit = (bd0p * np.pi * self.rock.ResE) / (-8.0 * (1.0 - self.rock.Resv ** 2.0) * f_radius)
        # hydropropped fracture with proppant pillars
        if (e_max < e_crit):
            # maximum aperture from Sneddon's (PKN) penny fracture aperture
            bdt = (-8.0 * e_max * (1.0 - self.rock.Resv ** 2.0) * f_radius) / (pi * self.rock.ResE)  # m
            # channel width ratios by filled volume to total volume
            wp_wt = bd0p / bdt
            wo_wt = 1.0 - wp_wt
            # flow through open channels
            qo = wo_wt * (self.faces[f_id].roughness * bdt) ** 3.0
            # flow through propped area
            qp = wp_wt * (12.0 * self.faces[f_id].kf * bdt)
            # flow through shear channels
            qs = (self.faces[f_id].u_N * bd0) ** 3.0
            # total dilated aperture
            bd = bdt + bd0
            # total hydraulic aperture
            bh = (qo + qp + qs) ** (1.0 / 3.0)
            # note that fracture is hydropropped
            self.faces[f_id].hydroprop = True
        # proppant propped fracture
        elif (e_max < 0.0):
            # flow through propped area
            qp = 12.0 * self.faces[f_id].kf * bd0p * np.exp(-self.faces[f_id].prop_alpha * (e_max - e_crit))
            # flow through shear channels
            qs = (self.faces[f_id].u_N * bd0) ** 3.0
            # total dilated aperture
            bd = bd0p * np.exp(-self.faces[f_id].prop_alpha * (e_max - e_crit)) + bd0
            # total hydraulic aperture
            bh = (qp + qs) ** (1.0 / 3.0)
            # note that fracture is not hydropropped
            self.faces[f_id].hydroprop = False
        # proppant propped fracture
        else:
            # flow through propped area
            qp = 12.0 * self.faces[f_id].kf * bd0p * np.exp(-self.faces[f_id].prop_alpha * (e_max - e_crit))
            # flow through shear channels
            qs = (self.faces[f_id].u_N * bd0 * np.exp(-self.faces[f_id].u_alpha * e_max)) ** 3.0
            # total dilated aperture
            bd = (bd0p * np.exp(-self.faces[f_id].prop_alpha * (e_max - e_crit)) +
                  bd0 * np.exp(-self.faces[f_id].u_alpha * e_max))
            # total hydraulic aperture
            bh = (qp + qs) ** (1.0 / 3.0)
            # note that fracture is not hydropropped
            self.faces[f_id].hydroprop = False

        # override for boundary fractures
        if (int(self.faces[f_id].typ) in [typ('boundary')]):
            bh = self.rock.bh_bound

        # volume
        vol = (4.0 / 3.0) * pi * 0.25 * self.faces[f_id].dia ** 2.0 * 0.5 * bd

        # update proppant loading
        dvol = vol - self.faces[f_id].vol
        self.faces[f_id].prop_load = self.faces[f_id].prop_load + np.max([0.0, dvol]) * self.rock.sand

        # update fracture properties
        self.faces[f_id].bd = bd
        self.faces[f_id].bh = bh
        self.faces[f_id].vol = vol
        self.faces[f_id].bd0 = bd0
        self.faces[f_id].bd0p = bd0p

        # return true if stimulated
        return stim

    # # L - d - M - k Gutenberg-Richter based aperture stimulation
    # def GR_bh(self, f_id, fix=False): #, pp=-666.0):
    #     #initialize stim
    #     stim = False

    #     #check if fracture will be stimulated
    #     if (self.faces[f_id].Pmax >= self.faces[f_id].Pc):
    #         self.faces[f_id].stim += 1
    #         stim = True
    #         print( '-> fracture stimulated: %i' %(f_id))

    #     #fracture parameters
    #     f_radius = 0.5*self.faces[f_id].dia

    #     #pressures for analysis
    #     e_max = self.faces[f_id].sn - self.faces[f_id].Pmax

    #             self.prop_load = 0.0 #m3 #absolute proppant volume
    #             self.prop_alpha = rock.prop_alpha #proppant compressibility modulus

    #     #stimulation disabled
    #     if not(stim) or fix:
    #         bd0 = self.faces[f_id].bd0
    #         #if open
    #         if (e_max < 0.0):
    #             #maximum aperture from Sneddon's (PKN) penny fracture aperture
    #             bd = (-8.0*e_max*(1.0-self.rock.Resv**2.0)*f_radius)/(pi*self.rock.ResE) #m
    #             #hydraulic aperture
    #             bh = bd*self.rock.f_roughness #m
    #             #add bd0 for equation continuity
    #             bd = bd + bd0
    #             bh = bh + bd0*self.faces[f_id].u_N
    #             #note that fracture is hydropropped
    #             self.faces[f_id].hydroprop = True
    #         #if closed
    #         else:
    #             #stress closure
    #             bd = bd0 * np.exp(-self.faces[f_id].u_alpha*e_max)
    #             #hydraulic aperture
    #             bh = bd * self.faces[f_id].u_N
    #             #note that fracture is closed
    #             self.faces[f_id].hydroprop = False
    #     #stimulation enabled
    #     else:
    #         #*** shear component ***
    #         #don't let shear be zero
    #         if self.faces[f_id].tau < 1.0:
    #             self.faces[f_id].tau = 1.0
    #         #maximum moment (shear stress method)
    #         #M0max = self.faces[f_id].tau*(0.25*np.pi*self.faces[f_id].dia**2.0)**(3.0/2.0)
    #         M0max = self.faces[f_id].tau*self.faces[f_id].arup**(3.0/2.0)
    #         Mwmax = (np.log10(M0max)-9.1)/1.5
    #         #mw sample from G-R
    #         mw = exponential_trunc(1,bval=self.rock.bval,Mmax=Mwmax,Mwin=1.0,prob=0.1)[0]
    #         #convert to moment magnitude (Mo)
    #         mo = 10.0**(mw * 1.5 + 9.1)
    #         # rupture length
    #         Lr = (4*((mo/self.faces[f_id].tau)**(2/3))/np.pi)**0.5
    #         # intermediate variables
    #         ds = mo / ((0.25*np.pi*Lr**2.0) * self.rock.ResG)
    #         d0 = 0.5 * self.faces[f_id].u_gamma * (self.faces[f_id].dia ** self.faces[f_id].u_n1)
    #         bd0 = self.faces[f_id].u_a * (d0 ** self.faces[f_id].u_b)
    #         d1 = d0 + ds
    #         bd1 = self.faces[f_id].u_a * (d1 ** self.faces[f_id].u_b)
    #         dbd = bd1- bd0
    #         #record stimulation magnitude and correct for seismic overestimation
    #         self.faces[f_id].Mws += [mw]
    #         #add to zero-stress dilatant aperture
    #         bd0 = self.faces[f_id].bd0 + dbd

    #         #*** tensile component ***
    #         #if open
    #         if (e_max < 0.0):
    #             #maximum aperture from Sneddon's (PKN) penny fracture aperture
    #             bd = (-8.0*e_max*(1.0-self.rock.Resv**2.0)*f_radius)/(pi*self.rock.ResE) #m
    #             #hydraulic aperture
    #             bh = bd*self.rock.f_roughness #m
    #             #add bd0 for equation continuity
    #             bd = bd + bd0
    #             bh = bh + bd0*self.faces[f_id].u_N
    #             #note that fracture is hydropropped
    #             self.faces[f_id].hydroprop = True
    #             #override rupture length with full length
    #             Lr = self.faces[f_id].dia
    #         #if closed
    #         else:
    #             #stress closure
    #             #bd = bd0 * np.exp(-self.faces[f_id].u_alpha*e_cen) #!!!
    #             bd = bd0 * np.exp(-self.faces[f_id].u_alpha*e_max)
    #             #hydraulic aperture
    #             bh = bd * self.faces[f_id].u_N
    #             #note that fracture is closed
    #             self.faces[f_id].hydroprop = False

    #         #*** growth ***
    #         #grow fracture by larger of 20% fracture size or 5% domain size #!!!
    #         add_dia = np.max([0.2*self.faces[f_id].dia,0.05*self.rock.size])
    #         #deduct event's rupture area from residual rupture area
    #         self.faces[f_id].arup = np.max([self.faces[f_id].arup - 0.25*np.pi*Lr**2.0,  0.1])
    #         #update rupture area
    #         self.faces[f_id].arup = self.faces[f_id].arup + 0.25*np.pi*((self.faces[f_id].dia + add_dia)**2.0 - self.faces[f_id].dia**2.0)
    #         #update fracture diameter
    #         self.faces[f_id].dia += add_dia

    #     # #limiters for flow solver stability #!!! limiters removed 02/13/23
    #     # if bh < self.rock.bh_min:
    #     #     bh = self.rock.bh_min
    #     #     # print( '-> Alert: bh at min')
    #     # elif bh > self.rock.bh_max:
    #     #     bh = self.rock.bh_max
    #     #     # print( '-> Alert: bh at max')

    #     #override for boundary fractures
    #     if (int(self.faces[f_id].typ) in [typ('boundary')]):
    #         bh = self.rock.bh_bound

    #     #volume
    #     vol = (4.0/3.0)*pi*0.25*self.faces[f_id].dia**2.0*0.5*bd

    #     #update fracture properties
    #     self.faces[f_id].bd = bd
    #     self.faces[f_id].bh = bh
    #     self.faces[f_id].vol = vol
    #     self.faces[f_id].bd0 = bd0

    #     #return true if stimulated
    #     return stim

    def save(self, fname='input_output.txt', pin='', aux=[], printwells=0, time=True):
        out = []

        out += [['pin', pin]]

        # input parameters
        r = self.rock
        out += [['size', r.size]]
        out += [['ResDepth', r.ResDepth]]
        out += [['ResGradient', r.ResGradient]]
        out += [['ResRho', r.ResRho]]
        out += [['ResKt', r.ResKt]]
        out += [['ResSv', r.ResSv]]
        out += [['AmbTempC', r.AmbTempC]]
        out += [['AmbPres', r.AmbPres]]
        out += [['ResE', r.ResE]]
        out += [['Resv', r.Resv]]
        out += [['ResG', r.ResG]]
        out += [['Ks3', r.Ks3]]
        out += [['Ks2', r.Ks2]]
        out += [['s3Azn', r.s3Azn]]
        out += [['s3AznVar', r.s3AznVar]]
        out += [['s3Dip', r.s3Dip]]
        out += [['s3DipVar', r.s3DipVar]]
        for i in range(0, len(r.fNum)):
            out += [['fNum%i' % (i), r.fNum[i]]]
            out += [['fDia_min%i' % (i), r.fDia[i][0]]]
            out += [['fDia_max%i' % (i), r.fDia[i][1]]]
            out += [['fStr_nom%i' % (i), r.fStr[i][0]]]
            out += [['fStr_var%i' % (i), r.fStr[i][1]]]
            out += [['fDip_nom%i' % (i), r.fDip[i][0]]]
            out += [['fDip_var%i' % (i), r.fDip[i][1]]]
        for i in range(0, 3):
            out += [['alpha%i' % (i), r.alpha[i]]]
        for i in range(0, 3):
            out += [['prop_alpha%i' % (i), r.prop_alpha[i]]]
        for i in range(0, 3):
            out += [['gamma%i' % (i), r.gamma[i]]]
        for i in range(0, 3):
            out += [['n1%i' % (i), r.n1[i]]]
        for i in range(0, 3):
            out += [['a%i' % (i), r.a[i]]]
        for i in range(0, 3):
            out += [['b%i' % (i), r.b[i]]]
        for i in range(0, 3):
            out += [['N%i' % (i), r.N[i]]]
        for i in range(0, 3):
            out += [['bh%i' % (i), r.bh[i]]]
        out += [['bh_min', r.bh_min]]
        out += [['bh_max', r.bh_max]]
        out += [['bh_bound', r.bh_bound]]

        # TODO verify that treating single float value as array of that value is OK/correct
        out_roughness = r.f_roughness
        if type(out_roughness) is float:
            out_roughness = [out_roughness] * 3
        for i in range(0, 3):
            out += [[f'f_roughness{i}', out_roughness[i]]]

        out += [['w_count', r.w_count]]
        out += [['w_spacing', r.w_spacing]]
        out += [['w_length', r.w_length]]
        out += [['w_azimuth', r.w_azimuth]]
        out += [['w_dip', r.w_dip]]
        out += [['w_proportion', r.w_proportion]]
        out += [['w_phase', r.w_phase]]
        out += [['w_toe', r.w_toe]]
        out += [['w_skew', r.w_skew]]
        out += [['w_intervals', r.w_intervals]]
        out += [['ra', r.ra]]
        out += [['rb', r.rb]]
        out += [['rc', r.rc]]
        out += [['rgh', r.rgh]]
        out += [['CemKt', r.CemKt]]
        out += [['CemSv', r.CemSv]]
        out += [['GenEfficiency', r.GenEfficiency]]
        out += [['LifeSpan', r.LifeSpan]]
        out += [['TimeSteps', r.TimeSteps]]
        out += [['p_whp', r.p_whp]]
        out += [['Tinj', r.Tinj]]
        out += [['H_ConvCoef', r.H_ConvCoef]]
        out += [['dT0', r.dT0]]
        # out += [['dE0',r.dE0]]
        out += [['PoreRho', r.PoreRho]]
        out += [['Poremu', r.Poremu]]
        out += [['Porek', r.Porek]]
        out += [['kf', r.kf]]
        out += [['BH_T', r.BH_T]]
        out += [['BH_P', r.BH_P]]
        out += [['s1', r.s1]]
        out += [['s2', r.s2]]
        out += [['s3', r.s3]]
        out += [['perf', r.perf]]
        out += [['r_perf', r.r_perf]]
        out += [['sand', r.sand]]
        # out += [['leakoff',r.leakoff]]
        out += [['dPp', r.dPp]]
        out += [['dPi', r.dPi]]
        out += [['stim_limit', r.stim_limit]]
        out += [['Qinj', r.Qinj]]
        out += [['Vinj', r.Vinj]]
        out += [['Qstim', r.Qstim]]
        out += [['Vstim', r.Vstim]]
        out += [['pfinal_max', r.pfinal_max]]
        out += [['bval', r.bval]]
        for i in range(0, 3):
            out += [['phi%i' % (i), r.phi[i]]]
        for i in range(0, 3):
            out += [['mcc%i' % (i), r.mcc[i]]]
        out += [['hfmcc', r.hfmcc]]
        out += [['hfphi', r.hfphi]]

        # auxillary printed inputs & outputs #!!!
        if aux:
            out += aux

        # total injection rate (+ in)
        qinj = 0.0
        key = np.where(np.asarray(self.i_q) > 0.0)[0]
        for i in key:
            qinj += self.i_q[i]
        key = np.where(np.asarray(self.p_q) > 0.0)[0]
        for i in key:
            qinj += self.p_q[i]
        out += [['qinj', qinj]]

        # total production rate (-out)
        qpro = 0.0
        key = np.where(np.asarray(self.i_q) < 0.0)[0]
        for i in key:
            qpro += self.i_q[i]
        key = np.where(np.asarray(self.p_q) < 0.0)[0]
        for i in key:
            qpro += self.p_q[i]
        out += [['qpro', qpro]]

        # total leakoff rate (-out)
        qoff = 0.0
        key = np.where(np.asarray(self.b_q) < 0.0)[0]
        for i in key:
            qoff += self.b_q[i]
        out += [['qleak', qoff]]

        # total boundary uptake (+in)
        qup = 0.0
        key = np.where(np.asarray(self.b_q) > 0.0)[0]
        for i in key:
            qup += self.b_q[i]
        out += [['qgain', qup]]

        # recovery
        qrec = 0.0
        if qinj > 0:
            qrec = -qpro / qinj
        else:
            qrec = 1.0
        out += [['recovery', qrec]]

        # largest quake
        quake = -10.0
        for i in range(0, len(self.faces)):
            if self.faces[i].Mws:
                quake = np.max([quake, np.max(self.faces[i].Mws)])
        out += [['max_quake', quake]]

        # injection pressure
        # pinj = np.max(np.asarray(self.p_p))/MPa
        pinj = np.max(self.nodes.p) / MPa
        out += [['pinj', pinj]]

        # injection enthalpy
        T5 = self.rock.Tinj + 273.15  # K
        if pinj > 100.0:
            pinj = 100.0
        try:
            state = therm(T=T5, P=pinj)
            hinj = state.h
        except:
            hinj = 0.0
        out += [['hinj', hinj]]

        # injection specific volume #!!!
        out += [['v5', self.v5]]

        # injection intercepts
        ixint = 0
        for i in range(0, self.pipes.num):
            if (int(self.pipes.typ[i]) in [typ('injector')]):
                ixint += 1
        ixint = ixint - self.rock.w_intervals
        out += [['ixint', ixint]]

        # production intercepts
        pxint = 0
        for i in range(0, self.pipes.num):
            if (int(self.pipes.typ[i]) in [typ('producer')]):
                pxint += 1
        pxint = pxint - self.rock.w_count
        out += [['pxint', pxint]]

        # stimulated fractures
        hfstim = 0
        nfstim = 0
        for i in range(0, len(self.faces)):
            if (self.faces[i].stim > 0):
                if (int(self.faces[i].typ) in [typ('propped')]):
                    hfstim += 1
                elif (int(self.faces[i].typ) in [typ('fracture')]):
                    nfstim += 1
        out += [['hfstim', hfstim]]
        out += [['nfstim', nfstim]]

        # injection mass flow rate
        out += [['minj', self.i_mm]]

        # production mass flow rate
        out += [['mpro', self.p_mm]]

        # production enthalpy over time
        for t in range(0, len(self.ts) - 1):
            out += [['hpro:%.3f' % (self.ts[t] / yr), self.p_hm[t]]]

        # flash power
        Pout = []
        if len(self.Pout) == 0:
            Pout = np.full(len(self.ts), np.nan)
        else:
            Pout = self.Pout
        for t in range(0, len(self.ts) - 1):
            out += [['Pout:%.3f' % (self.ts[t] / yr), Pout[t]]]

        # #binary power
        # Bout = []
        # if self.Bout == []:
        #     Bout = np.full(len(self.ts),np.nan)
        # else:
        #     Bout = self.Bout
        # for t in range(0,len(self.ts)-1):
        #     out += [['Bout:%.3f' %(self.ts[t]/yr),Bout[t]]]

        # #thermal energy extraction
        # dhout = []
        # self.dhout = np.asarray(self.dhout)
        # if not self.dhout.any():
        #     dhout = np.full(len(self.ts),np.nan)
        # else:
        #     dhout = self.dhout
        # for t in range(0,len(self.ts)-1):
        #     out += [['dhout:%.3f' %(self.ts[t]/yr),dhout[t]]]

        # per well values
        if (printwells != 0) and (self.w_m.any()):
            # #per well volume flow rate
            # dummy = np.zeros(20,dtype=float)
            # for i in range(0,len(self.p_q)):
            #     if i > 20:
            #         print('warning: number of wells exceeds placeholder of 20 so not all values will be printed')
            #         break
            #     dummy[i] = self.p_q[i]
            # for i in range(0,len(dummy)):
            #     out += [['q%i' %(i),dummy[i]]]

            # collect well temp (T), volume rate (q), mass rate (m), and enthalpy (h)
            w_h = []
            w_T = []
            w_m = []
            w_q = []
            for w in range(0, len(self.wells)):
                # coordinates
                source = self.wells[w].c0
                # find index of duplicate
                ck, i = self.nodes.add(source)
                # record temperature
                w_T += [self.Tt[:, i]]
                # record enthalpy
                w_h += [self.ht[:, i]]
                # record mass flow rate
                i_pipe = np.where(np.asarray(self.pipes.n0) == i)[0][0]
                w_m += [self.q[i_pipe] / self.v5]
                # record volume flow rate
                w_q += [self.q[i_pipe]]
            w_h = np.asarray(w_h)
            w_T = np.asarray(w_T)
            w_m = np.asarray(w_m)
            w_q = np.asarray(w_q)

            # per well mass flow rate #!!!
            max_w = printwells
            w_q_s = np.zeros(max_w, dtype=float)
            w_m_s = np.zeros(max_w, dtype=float)
            w_T_s = np.zeros((max_w, r.TimeSteps - 1), dtype=float)
            w_h_s = np.zeros((max_w, r.TimeSteps - 1), dtype=float)
            if len(self.wells) > max_w:
                print(
                    f'warning: number of wells exceeds specified output number of {max_w} so not all values will be printed')
            # use array math to store values in fixed-width arrays
            if self.wells:  # error handling for case with no wells
                n = np.min([len(self.wells), max_w])
                w_q_s[:n] = w_q_s[:n] + w_q[:n]
                w_m_s[:n] = w_m_s[:n] + w_m[:n]
                w_T_s[:n] = w_T_s[:n, :] + w_T[:n, :-2]
                w_h_s[:n] = w_h_s[:n, :] + w_h[:n, :-2]
            # rearrange into single-line format
            for w in range(0, max_w):
                # volume flow rate, m3/s
                out += [['q%i' % (w), w_q_s[w]]]
                # mass flow rate, kg/s
                out += [['m%i' % (w), w_m_s[w]]]
                if time:
                    for t in range(0, r.TimeSteps - 1):
                        # temperature over time, K
                        out += [['T%i:%.3f' % (w, self.ts[t] / yr), w_T_s[w, t]]]
                    for t in range(0, r.TimeSteps - 1):
                        # enthalpy over time, h
                        out += [['h%i:%.3f' % (w, self.ts[t] / yr), w_h_s[w, t]]]

        # output to file
        if fname.endswith('.txt'):
            # out = zip(*out)
            out = list(map(list, zip(*out)))
            head = out[0][0]
            for i in range(1, len(out[0])):
                head = head + ',' + out[0][i]
            data = str(out[1][0])
            for i in range(1, len(out[1])):
                if not out[1][i]:
                    data = data + ',0.0'  # ',nan'
                else:
                    data = data + ',%.5e' % (out[1][i])
            try:
                with open(fname, 'r') as f:
                    test = f.readline()
                f.close()
                if test != '':
                    with open(fname, 'a') as f:
                        f.write(data + '\n')
                    f.close()
                else:
                    with open(fname, 'a') as f:
                        f.write(head + '\n')
                        f.write(data + '\n')
                    f.close()
            except:
                with open(fname, 'a') as f:
                    f.write(head + '\n')
                    f.write(data + '\n')
                f.close()
        elif fname.endswith('.csv'):
            with open(fname,'a') as f:
                f.write('Key,Value\n')
                for out_kv_pair in out:
                    key = out_kv_pair[0]
                    value = out_kv_pair[1]
                    f.write(f'{key},{value}\n')

            f.close()
        else:
            raise ValueError('Invalid file extension')


    #
    #        return out

    def build_vtk(self, fname='default', vtype=[1, 1, 1, 1, 1, 1]):
        # ******   scaling       ******
        r = 0.002 * self.rock.size

        # ******   paint wells   ******
        if vtype[0]:
            w_obj = []  # fractures
            w_col = []  # fractures colors
            w_lab = []  # fractures color labels
            w_lab = ['Well_Number', 'Well_Type', 'Inner_Radius', 'Roughness', 'Outer_Radius']
            w_0 = []
            w_1 = []
            w_2 = []
            w_3 = []
            w_4 = []
            # nodex = np.asarray(self.nodes)
            for i in range(0, len(self.wells)):  # skip boundary node at np.inf
                # add colors
                w_0 += [i]
                w_1 += [self.wells[i].typ]
                w_2 += [self.wells[i].ra]
                w_3 += [self.wells[i].rgh]
                w_4 += [self.wells[i].rc]
                # add geometry
                azn = self.wells[i].azn
                dip = self.wells[i].dip
                leg = self.wells[i].leg
                vAxi = np.asarray([math.sin(azn) * math.cos(-dip), math.cos(azn) * math.cos(-dip), math.sin(-dip)])
                c0 = self.wells[i].c0
                c1 = c0 + vAxi * leg
                w_obj += [sg.cylObj(x0=c0, x1=c1, r=1.5 * r)]
            # vtk file
            w_col = [w_0, w_1, w_2, w_3, w_4]
            sg.writeVtk(w_obj, w_col, w_lab, vtkFile=(fname + '_wells.vtk'))

        # ******   paint fractures   ******
        if vtype[1] and len(self.faces) > 6:
            f_obj = []  # fractures
            f_col = []  # fractures colors
            f_lab = []  # fractures color labels
            f_lab = ['Face_Number', 'Node_Number', 'Type', 'Sn_MPa', 'Pc_MPa', 'Tau_MPa']
            f_0 = []
            f_1 = []
            f_2 = []
            f_3 = []
            f_4 = []
            f_5 = []
            # nodex = np.asarray(self.nodes)
            for i in range(6, len(self.faces)):  # skip boundary node at np.inf
                # add colors
                f_0 += [i]
                f_1 += [self.faces[i].ci]
                f_2 += [self.faces[i].typ]
                f_3 += [self.faces[i].sn / MPa]
                f_4 += [self.faces[i].Pc / MPa]
                f_5 += [self.faces[i].tau / MPa]
                # add geometry
                f_obj += [HF(r=0.5 * self.faces[i].dia, x0=self.faces[i].c0, strikeRad=self.faces[i].str,
                             dipRad=self.faces[i].dip, h=0.01 * r)]
            # vtk file
            f_col = [f_0, f_1, f_2, f_3, f_4, f_5]
            sg.writeVtk(f_obj, f_col, f_lab, vtkFile=(f'{fname}_fracs.vtk'))

        # ******   paint flowing fractures   ******
        if vtype[2] and len(self.faces) > 6:
            q_obj = []  # fractures
            q_col = []  # fractures colors
            q_lab = []  # fractures color labels
            q_lab = ['Face_Number', 'Node_Number', 'Type', 'Dilation_mm', 'Hydraulic_mm', 'Sn_MPa', 'Pcen_MPa',
                     'Pc_MPa', 'stim', 'Pmax_MPa', 'Tau_MPa', 'Mwmax', 'Propped_mm', 'Prop_m3']
            q_0 = []
            q_1 = []
            q_2 = []
            q_3 = []
            q_4 = []
            q_5 = []
            q_6 = []
            q_7 = []
            q_8 = []
            q_9 = []
            q_10 = []
            q_11 = []
            q_12 = []
            q_13 = []
            # nodex = np.asarray(self.nodes)
            for i in range(6, len(self.faces)):  # skip boundary node at np.inf
                if self.faces[i].ci >= 0:
                    # add colors
                    q_0 += [i]
                    q_1 += [self.faces[i].ci]
                    q_2 += [self.faces[i].typ]
                    q_3 += [self.faces[i].bd * 1000]
                    q_4 += [self.faces[i].bh * 1000]
                    q_5 += [self.faces[i].sn / MPa]
                    q_6 += [self.faces[i].Pcen]
                    q_7 += [self.faces[i].Pc / MPa]
                    q_8 += [self.faces[i].stim]
                    q_9 += [self.faces[i].Pmax]
                    q_10 += [self.faces[i].tau / MPa]
                    q_11 += [np.max(self.faces[i].Mws)]
                    q_12 += [self.faces[i].bd0p * 1000]
                    q_13 += [self.faces[i].prop_load]
                    # add geometry
                    q_obj += [HF(r=0.5 * self.faces[i].dia, x0=self.faces[i].c0, strikeRad=self.faces[i].str,
                                 dipRad=self.faces[i].dip, h=0.02 * r)]
            # vtk file
            q_col = [q_0, q_1, q_2, q_3, q_4, q_5, q_6, q_7, q_8, q_9, q_10, q_11, q_12, q_13]
            sg.writeVtk(q_obj, q_col, q_lab, vtkFile=(fname + '_fnets.vtk'))

        # ******   paint nodes   ******
        if vtype[3]:
            n_obj = []  # nodes
            n_col = []  # nodes colors
            n_lab = []  # nodes color labels
            n_lab = ['Node_Number', 'Node_Pressure_MPa', 'Node_Temperature_K', 'Node_Enthalpy_kJ/kg']
            n_0 = []
            n_1 = []
            n_2 = []
            n_3 = []
            # nodex = np.asarray(self.nodes)
            for i in range(1, self.nodes.num):  # skip boundary node at np.inf
                # add colors
                n_0 += [i]
                n_1 += [self.nodes.p[i] / MPa]
                n_2 += [self.nodes.T[i]]
                n_3 += [self.nodes.h[i]]
                # add geometry
                n_obj += [sg.cylObj(x0=self.nodes.all[i] + np.asarray([0.0, 0.0, -r]),
                                    x1=self.nodes.all[i] + np.asarray([0.0, 0.0, r]), r=r)]
            # vtk file
            n_col = [n_0, n_1, n_2, n_3]
            sg.writeVtk(n_obj, n_col, n_lab, vtkFile=(fname + '_nodes.vtk'))

        # ******   paint pipes   ******
        if vtype[4]:
            p_obj = []  # pipes
            p_col = []  # pipes colors
            p_lab = []  # pipes color labels
            p_lab = ['Pipe_Number', 'Type', 'Pipe_Flow_Rate_m3_s', 'Height_m', 'Length_m', 'Hydraulic_Aperture_mm',
                     'Max_Aperture_mm', 'Friction']
            p_0 = []
            p_1 = []
            p_2 = []
            p_3 = []
            p_4 = []
            p_5 = []
            p_6 = []
            p_7 = []
            qs = np.asarray(self.q)
            if not qs.any():
                qs = np.zeros(self.pipes.num)
            qs = np.abs(qs)
            for i in range(0, self.pipes.num):
                # add geometry
                x0 = self.nodes.all[self.pipes.n0[i]]
                x1 = self.nodes.all[self.pipes.n1[i]]
                # don't include boundary node
                if not (np.isinf(x0[0]) or np.isinf(x1[0])):
                    p_obj += [sg.cylObj(x0=x0, x1=x1, r=0.666 * r)]
                    # add colors
                    p_0 += [i]
                    p_1 += [self.pipes.typ[i]]
                    p_2 += [qs[i]]
                    p_3 += [self.pipes.W[i]]
                    p_4 += [self.pipes.L[i]]
                    p_5 += [self.pipes.Dh[i] * 1000]
                    p_6 += [self.pipes.Dh_max[i] * 1000]
                    p_7 += [self.pipes.frict[i]]
            # vtk file
            p_col = [p_0, p_1, p_2, p_3, p_4, p_5, p_6, p_7]
            sg.writeVtk(p_obj, p_col, p_lab, vtkFile=(fname + '_flow.vtk'))

        # ******   paint boundaries   ******
        if vtype[5]:
            f_obj = []  # fractures
            f_col = []  # fractures colors
            f_lab = []  # fractures color labels
            f_lab = ['Face_Number', 'Node_Number', 'Type', 'Sn_MPa', 'Pc_MPa', 'Tau_MPa']
            f_0 = []
            f_1 = []
            f_2 = []
            f_3 = []
            f_4 = []
            f_5 = []
            # nodex = np.asarray(self.nodes)
            for i in range(0, 6):  # skip boundary node at np.inf
                # add colors
                f_0 += [i]
                f_1 += [self.faces[i].ci]
                f_2 += [self.faces[i].typ]
                f_3 += [self.faces[i].sn / MPa]
                f_4 += [self.faces[i].Pc / MPa]
                f_5 += [self.faces[i].tau / MPa]
                # add geometry
                f_obj += [HF(r=0.5 * self.faces[i].dia, x0=self.faces[i].c0, strikeRad=self.faces[i].str,
                             dipRad=self.faces[i].dip, h=0.01 * r)]
            # vtk file
            f_col = [f_0, f_1, f_2, f_3, f_4, f_5]
            sg.writeVtk(f_obj, f_col, f_lab, vtkFile=(fname + '_bounds.vtk'))

    def build_pts(self, spacing=25.0, fname='test_gridx'):
        print('*** constructing temperature grid ***')
        # structured grid of datapoints
        fname = fname + '_therm.vtk'
        size = self.rock.size
        num = int(2.0 * size / spacing) + 1
        label = 'temp_K'
        ns = [num, num, num]
        o0 = [-size, -size, -size]
        ss = [spacing, spacing, spacing]

        # initialize data to initial rock temperature
        data = np.ones((num, num, num), dtype=float) * self.rock.BH_T

        # seek temperature drawdown
        for i in range(0, self.pipes.num):
            print(f'pipe {i}')
            # collect fracture parameters
            x0 = self.nodes.all[self.pipes.n0[i]]
            x1 = self.nodes.all[self.pipes.n1[i]]
            T0 = self.nodes.T[self.pipes.n0[i]]
            T1 = self.nodes.T[self.pipes.n1[i]]
            c0 = 0.5 * (x0 + x1)
            r0 = 0.5 * np.linalg.norm(x1 - x0)
            R0 = self.R0[i]
            # pipes and wells
            if (int(self.pipes.typ[i]) in [typ('injector'), typ('producer'),
                                           typ('pipe')]):  # ((Y[i][2] == 0): #pipe, Hazen-Williams
                pass
            # fractures and planes
            elif (int(self.pipes.typ[i]) in [typ('fracture'), typ('propped'),
                                             typ('choke')]):  # (int())Y[i][2] == 1: #fracture, effective cubic law
                # fracture info
                dip = self.faces[self.pipes.fID[i]].dip
                azn = self.faces[self.pipes.fID[i]].str
                vNor = np.asarray(
                    [math.sin(azn + 90.0 * deg) * math.sin(dip), math.cos(azn + 90.0 * deg) * math.sin(dip),
                     math.cos(dip)])
                vLeg = (x1 - c0) / np.linalg.norm(x1 - c0)
                vWid = np.cross(vNor, vLeg)
                # cycle thruogh all points
                for x in range(0, len(data)):
                    for y in range(0, len(data[0])):
                        for z in range(0, len(data[0, 0])):
                            # point coordinates
                            xPt = np.asarray([o0[0] + x * spacing, o0[1] + y * spacing, o0[2] + z * spacing])
                            # spherical radius vector
                            pi = xPt - c0
                            # normal distance from fracture
                            ni = np.linalg.norm(np.dot(pi, vNor))
                            # lengthwise distance from fracture
                            li = np.linalg.norm(np.dot(pi, vLeg))
                            # widthwise distance from fracture
                            wi = np.linalg.norm(np.dot(pi, vWid))
                            # if within length, width, normal
                            if (ni <= R0) and (li <= r0) and (wi <= (0.5 * self.pipes.W[i])):
                                # subtract delta T at point based on distance of point versus thermal radius
                                data[x, y, z] = data[x, y, z] + (0.5 * (T1 + T0) - self.rock.BH_T) * (1.0 - ni / R0)

        head = '# vtk DataFile Version 2.0\n'
        head += 'pointcloud\n'
        head += 'ASCII\n'
        head += 'DATASET STRUCTURED_POINTS\n'
        head += 'DIMENSIONS %i %i %i\n' % (ns[0], ns[1], ns[2])
        head += 'ORIGIN %f %f %f\n' % (o0[0], o0[1], o0[2])
        head += 'SPACING %f %f %f\n' % (ss[0], ss[1], ss[2])
        head += 'POINT_DATA %i\n' % (ns[0] * ns[1] * ns[2])
        head += 'SCALARS ' + label + ' float 1\n'
        head += 'LOOKUP_TABLE default'

        print(head)

        try:
            with open(fname, 'r') as f:
                test = f.readline()
            f.close()
            if test != '':
                print('file already exists')
                f.close()
            else:
                with open(fname, 'a') as f:
                    f.write(head + '\n')
                    out = ''
                    for k in range(0, len(data[0, 0, :])):
                        for j in range(0, len(data[0, :, 0])):
                            for i in range(0, len(data[:, 0, 0])):
                                out += '%e' % (data[i, j, k]) + '\n'
                    f.write(out)
                f.close()
        except:
            with open(fname, 'a') as f:
                f.write(head + '\n')
                out = ''
                for k in range(0, len(data[0, 0, :])):
                    for j in range(0, len(data[0, :, 0])):
                        for i in range(0, len(data[:, 0, 0])):
                            out += '%e' % (data[i, j, k]) + '\n'
                f.write(out)
            f.close()

    def re_init(self):
        # clear prior data
        self.nodes = []
        self.nodes = Nodes()
        self.pipes = []
        self.pipes = Pipes()
        self.faces = []  # all surfaces
        self.faces = self.bound + self.fracs + self.hydfs
        for i in range(0, len(self.faces)):
            self.faces[i].ci = -1
        self.trakr = []
        self.H = []
        self.Q = []
        #        self.p = []
        self.nodes.p = self.nodes.p * 0.0
        self.nodes.T = self.nodes.T * 0.0
        self.nodes.h = self.nodes.h * 0.0
        self.q = []
        # self.bd = []
        # self.bh = []
        # self.sn = []
        #        self.f2n = []
        #        self.fp = []
        # self.static_KQn()
        return self

    def set_bcs(self, p_bound=0.0 * MPa, q_well=[], p_well=[]):
        # working variables
        rho = self.rock.PoreRho  # kg/m3
        # input & output boundaries
        self.H = []
        self.Q = []
        # outer boundary (always zero index node)
        self.H += [[0, p_bound / (rho * g)]]
        # well boundaries (lists with empty elements)
        # q_well = [None,  None, 0.02,  None]
        # p_well = [None, 3.0e6, None, 1.0e6]
        # default = p_bound
        for w in range(0, len(self.wells)):
            # identify boundary node
            # coordinates
            source = self.wells[w].c0
            # find index of duplicate
            ck, i = self.nodes.add(source)
            if not (ck):  # yes duplicate
                # prioritize flow boundary conditions
                if q_well[w] != None:
                    self.Q += [[i, -q_well[w]]]
                # pressure boundary conditions
                elif p_well[w] != None:
                    self.H += [[i, p_well[w] / (rho * g)]]
                # default to outer boundary condition if no boundary condition is explicitly stated
                else:
                    self.H += [[i, p_bound / (rho * g)]]
                    print('warning: a well was assigned the far-field pressure boundary condition')
            else:
                print('error: flow boundary point not identified')

    def therm_bcs(self, T_bound=0.0, T_inlet=[]):
        #        #search array
        #        narr = np.asarray(self.nodes)

        # outer boundary (always zero index node)
        self.Tb += [[0, T_bound]]

        # boundary conditions from wells
        n = 0
        for w in range(0, len(self.wells)):
            # temperature boundary condition
            if (self.wells[w].typ == typ('injector')):
                # coordinates
                source = self.wells[w].c0

                # find index of duplicate
                ck, i = self.nodes.add(source)
                if not (ck):  # yes duplicate
                    if len(T_inlet) > 1:
                        self.Tb += [[i, T_inlet[n]]]
                        n += 1
                    else:
                        self.Tb += [[i, T_inlet[0]]]
                else:
                    print('error: pressure temperature point not identified')

    def add_flowpath(self, source, target, length, width, featTyp, featID, Dh=1.0, Dh_max=1.0, frict=1.0):
        #        #ignore if source == target
        #        if list(source) == list(target):
        #            return -1, -1
        # source node
        n_s, so_n = self.nodes.add(source)  # ,f_id=featID)
        # target node
        n_t, ta_n = self.nodes.add(target)  # ,f_id=featID)
        # check if source is same as target
        if so_n == ta_n:
            return -1, -1
        # check if the reversed node set already exists (i.e., don't create pipes forward and backward between same nodes)
        if not (n_s) and not (n_t):
            to_ck = np.where(np.asarray(self.pipes.n0) == ta_n)[0]
            if len(to_ck) > 0:
                for i in to_ck:
                    if self.pipes.n1[i] == so_n:
                        return -1, -1
        # add pipe
        self.pipes.add(so_n, ta_n, length, width, featTyp, featID, Dh, Dh_max, frict)
        return so_n, ta_n

    # intersections of lines with lines
    def x_well_wells(self):
        pass

    # intersections of a line with a plane
    def x_well_all_faces(self, plot=True, sourceID=0, targetID=[],
                         offset=[]):  # , path_type=0, aperture=0.22, roughness=80.0): #[x0,y0,zo,len,azn,dip]
        # scaled visual offset
        if not (offset):
            offset = np.max([5.0 * self.nodes.tol, 0.010 * self.rock.size]) * np.asarray([0.58, 0.58, 0.58])

        # working array for finding and logging intersection points
        x_well = []  # intercept coord
        o_frac = []  # surface origin
        r_frac = []  # index of well
        i_frac = []  # index of frac

        # line location
        c0 = self.wells[sourceID].c0  # line origin
        leg = self.wells[sourceID].leg  # line length
        azn = self.wells[sourceID].azn  # line azimuth
        dip = self.wells[sourceID].dip  # line dip
        dia = self.wells[sourceID].ra  # line inner diameter
        lty = self.wells[sourceID].typ  # line type
        vAxi = np.asarray([math.sin(azn) * math.cos(-dip), math.cos(azn) * math.cos(-dip), math.sin(-dip)])
        cm = c0 + 0.5 * leg * vAxi  # line midpoint
        c1 = c0 + leg * vAxi  # line endpoint

        # for all target faces
        for targetID in range(0, len(self.faces)):
            # planar object parameters
            t0 = self.faces[targetID].c0  # face origin
            rad = 0.5 * self.faces[targetID].dia  # face diameter
            azn = self.faces[targetID].str  # face strike
            dip = self.faces[targetID].dip  # face dip
            fty = self.faces[targetID].typ  # face type
            # vDip = np.asarray([math.sin(azn+90.0*deg)*math.cos(-dip),math.cos(azn+90.0*deg)*math.cos(-dip),math.sin(-dip)])
            # vAzn = np.asarray([math.sin(azn),math.cos(azn),0.0])
            vNor = np.asarray(
                [math.sin(azn + 90.0 * deg) * math.sin(dip), math.cos(azn + 90.0 * deg) * math.sin(dip), math.cos(dip)])
            # infinite plane intersection point
            if np.dot(vNor, vAxi) != 0:  # not parallel
                x_test = c0 + vAxi * (np.dot(vNor, t0) - np.dot(vNor, c0)) / (np.dot(vNor, vAxi))

                # test for intersect within plane and line extents
                if (np.linalg.norm(cm - x_test) < (0.5 * leg)) and (np.linalg.norm(t0 - x_test) < (rad)):
                    x_well += [x_test]
                    o_frac += [t0]
                    r_frac += [rad]
                    i_frac += [targetID]
                    #                    fs_i += [targetID]
                    self.trakr += [[-1, targetID]]
        # in case of no intersections
        # add_flowpath(self, source, target, length, width, featTyp, featID, tol = 0.001):
        if len(x_well) == 0:
            # add endpoint to endpoint
            self.add_flowpath(c0,
                              c1 + offset,
                              leg,
                              dia,
                              lty,
                              sourceID,
                              Dh=dia,
                              Dh_max=dia,
                              frict=self.wells[sourceID].rgh)
            # return False
            return False
        # in case of intersections
        else:
            # convert to array
            x_well = np.asarray(x_well)

            # sort intersections by distance from origin point
            rs = []
            rs = np.linalg.norm(x_well - c0, axis=1)
            a = rs.argsort()
            # first element well (a live end)
            self.add_flowpath(c0,
                              x_well[a[0]] + offset,
                              rs[a[0]],
                              dia,
                              lty,
                              sourceID,
                              Dh=dia,
                              Dh_max=dia,
                              frict=self.wells[sourceID].rgh)
            # intersection points
            i = 0
            for i in range(0, len(rs) - 1):
                # #well-well links (+1.0 z offset to prevent non-real links from fracture to well without a choke)
                # self.add_flowpath(x_well[a[i]] + offset,
                #                   x_well[a[i+1]] + offset,
                #                   rs[a[i+1]]-rs[a[i]],
                #                   dia,
                #                   lty,
                #                   sourceID,
                #                   Dh=dia,
                #                   Dh_max=dia,
                #                   frict=self.wells[sourceID].rgh)
                # choke (circumference of well * 3.0 * diameter = near well flow channel area dimensions, otherwise properties of the fracture)
                self.add_flowpath(x_well[a[i]] + offset,
                                  x_well[a[i]],  # + offset*0.5,
                                  # 3.0*dia,
                                  # math.pi*dia,
                                  3.0 * self.wells[sourceID].rc,
                                  math.pi * self.wells[sourceID].rc,
                                  typ('choke'),
                                  i_frac[a[i]],
                                  Dh=self.faces[i_frac[a[i]]].bh,
                                  Dh_max=self.faces[i_frac[a[i]]].bh,
                                  frict=self.faces[i_frac[a[i]]].roughness)
                # fracture (use intercept to center length, but fix width to y at 1/2 cirle radius)
                self.add_flowpath(x_well[a[i]],  # + offset*0.5,
                                  o_frac[a[i]],
                                  np.linalg.norm(o_frac[a[i]] - (x_well[a[i]])),  # +offset*0.5)),
                                  0.866 * r_frac[a[i]],
                                  fty,
                                  i_frac[a[i]],
                                  Dh=self.faces[i_frac[a[i]]].bh,
                                  Dh_max=self.faces[i_frac[a[i]]].bh,
                                  frict=self.faces[i_frac[a[i]]].roughness)
                # well continued (+1.0 z offset to prevent non-real links from fracture to well without a choke)
                self.add_flowpath(x_well[a[i]] + offset,
                                  x_well[a[i + 1]] + offset,
                                  rs[a[i + 1]] - rs[a[i]],
                                  dia,
                                  lty,
                                  sourceID,
                                  Dh=dia,
                                  Dh_max=dia,
                                  frict=self.wells[sourceID].rgh)
                # store fracture centerpoint node number
                ck, cki = self.nodes.add(o_frac[a[i]])
                self.faces[i_frac[a[i]]].ci = cki

            # last segment choke
            self.add_flowpath(x_well[a[-1]] + offset,
                              x_well[a[-1]],  # + offset*0.5,
                              # 3.0*dia,
                              # math.pi*dia,
                              3.0 * self.wells[sourceID].rc,
                              math.pi * self.wells[sourceID].rc,
                              typ('choke'),
                              i_frac[a[-1]],
                              Dh=self.faces[i_frac[a[-1]]].bh,
                              Dh_max=self.faces[i_frac[a[-1]]].bh,
                              frict=self.faces[i_frac[a[-1]]].roughness)
            # last segment fracture
            self.add_flowpath(x_well[a[-1]],  # + offset*0.5,
                              o_frac[a[-1]],
                              np.linalg.norm(o_frac[a[-1]] - (x_well[a[-1]])),  # +offset*0.5)),
                              0.866 * r_frac[a[-1]],
                              fty,
                              i_frac[a[i]],
                              Dh=self.faces[i_frac[a[-1]]].bh,
                              Dh_max=self.faces[i_frac[a[-1]]].bh,
                              frict=self.faces[i_frac[a[-1]]].roughness)
            # dead end segment
            self.add_flowpath(x_well[a[-1]] + offset,
                              c1,
                              np.linalg.norm(x_well[a[-1]] - c1),  # ,axis=1),
                              dia,
                              lty,
                              sourceID,
                              Dh=dia,
                              Dh_max=dia,
                              frict=self.wells[sourceID].rgh)
            # store fracture centerpoint node number
            ck, cki = self.nodes.add(o_frac[a[i]])
            self.faces[i_frac[a[-1]]].ci = cki
            return True

            #     # #original code
            #     #well-well links (+1.0 z offset to prevent non-real links from fracture to well without a choke)
            #     self.add_flowpath(x_well[a[i]] + offset,
            #                       x_well[a[i+1]] + offset,
            #                       rs[a[i+1]]-rs[a[i]],
            #                       dia,
            #                       lty,
            #                       sourceID)
            #     #well-choke links (circumference of well * 3.0 * diameter = near well flow channel area dimensions, otherwise properties of the fracture)
            #     self.add_flowpath(x_well[a[i]] + offset,
            #                       x_well[a[i]] + offset*0.5,
            #                       #3.0*dia,
            #                       #math.pi*dia,
            #                       3.0*self.wells[sourceID].rc,
            #                       math.pi*self.wells[sourceID].rc,
            #                       typ('choke'),
            #                       i_frac[a[i]])
            #     #choke-fracture-center links (use intercept to center length, but fix width to y at 1/2 cirle radius)
            #     p_1, p_2 = self.add_flowpath(x_well[a[i]] + offset*0.5,
            #                       o_frac[a[i]],
            #                       np.linalg.norm(o_frac[a[i]]-(x_well[a[i]]+offset*0.5)),
            #                       0.866*r_frac[a[i]],
            #                       fty,
            #                       i_frac[a[i]])
            #     #store fracture centerpoint node number
            #     if p_2 >= 0:
            #         self.faces[i_frac[a[i]]].ci = p_2
            # #last segment well-choke link
            # self.add_flowpath(x_well[a[-1]] + offset,
            #                  x_well[a[-1]] + offset*0.5,
            #                  #3.0*dia,
            #                  #math.pi*dia,
            #                  3.0*self.wells[sourceID].rc,
            #                  math.pi*self.wells[sourceID].rc,
            #                  typ('choke'),
            #                  i_frac[a[-1]])
            # #last segment choke-fracture link
            # p_1, p_2 = self.add_flowpath(x_well[a[-1]] + offset*0.5,
            #                  o_frac[a[-1]],
            #                  np.linalg.norm(o_frac[a[-1]]-(x_well[a[-1]]+offset*0.5)),
            #                  0.866*r_frac[a[-1]],
            #                  fty,
            #                  i_frac[a[i]])
            # #dead end segment
            # self.add_flowpath(x_well[a[-1]] + offset,
            #                   c1,
            #                   np.linalg.norm(x_well[a[-1]]-c1), #,axis=1),
            #                   dia,
            #                   lty,
            #                   sourceID)
            # #store fracture centerpoint node number
            # if p_2 >= 0:
            #     self.faces[i_frac[a[-1]]].ci = p_2
            # return True

    # intersections of a plane with a plane
    def x_frac_face(self, plot=True, sourceID=0, targetID=1):  # [x0,y0,z0,dia,azn,dip]
        # plane 1
        dia1 = 0.5 * self.faces[sourceID].dia
        dip = self.faces[sourceID].dip
        azn = self.faces[sourceID].str
        vNor1 = np.asarray(
            [math.sin(azn + 90.0 * deg) * math.sin(dip), math.cos(azn + 90.0 * deg) * math.sin(dip), math.cos(dip)])
        c01 = self.faces[sourceID].c0
        f1_t = self.faces[sourceID].typ

        # plane 2
        dia2 = 0.5 * self.faces[targetID].dia
        dip = self.faces[targetID].dip
        azn = self.faces[targetID].str
        vNor2 = np.asarray(
            [math.sin(azn + 90.0 * deg) * math.sin(dip), math.cos(azn + 90.0 * deg) * math.sin(dip), math.cos(dip)])
        c02 = self.faces[targetID].c0
        f2_t = self.faces[targetID].typ

        # intersection vector
        vInt = []
        vInt = np.cross(vNor1, vNor2)

        # if not parallel
        if np.dot(vNor1, vNor2) < 0.999999:
            # intersection vector origin point
            zero = np.argmax(np.abs(np.asarray(vInt)), axis=0)
            d1 = -1 * (vNor1[0] * c01[0] + vNor1[1] * c01[1] + vNor1[2] * c01[2])
            d2 = -1 * (vNor2[0] * c02[0] + vNor2[1] * c02[1] + vNor2[2] * c02[2])
            vN1 = np.delete(vNor1, zero, axis=0)
            vN2 = np.delete(vNor2, zero, axis=0)
            cInt = (np.asarray([np.linalg.det([[vN1[1], vN2[1]], [d1, d2]]),
                                np.linalg.det([[d1, d2], [vN1[0], vN2[0]]])])
                    / np.linalg.det([[vN1[0], vN2[0]], [vN1[1], vN2[1]]]))
            cInt = np.insert(cInt, zero, 0.0, axis=0)

            # endpoints - plane 1 intersection
            c = (cInt[0] - c01[0]) ** 2.0 + (cInt[1] - c01[1]) ** 2.0 + (cInt[2] - c01[2]) ** 2.0 - dia1 ** 2.0
            b = 2.0 * ((cInt[0] - c01[0]) * vInt[0] + (cInt[1] - c01[1]) * vInt[1] + (cInt[2] - c01[2]) * vInt[2])
            a = vInt[0] ** 2.0 + vInt[1] ** 2.0 + vInt[2] ** 2.0
            if (b ** 2.0 - 4.0 * a * c) >= 0.0:
                l1 = (-b + (b ** 2.0 - 4.0 * a * c) ** 0.5) / (2.0 * a)
                l2 = (-b - (b ** 2.0 - 4.0 * a * c) ** 0.5) / (2.0 * a)
                f1a = cInt + l1 * vInt
                f1b = cInt + l2 * vInt
            else:
                f1a = np.asarray([np.nan, np.nan, np.nan])
                f1b = np.asarray([np.nan, np.nan, np.nan])

                # endpoints - plane 2 intersection
            c = (cInt[0] - c02[0]) ** 2.0 + (cInt[1] - c02[1]) ** 2.0 + (cInt[2] - c02[2]) ** 2.0 - dia2 ** 2.0
            b = 2.0 * ((cInt[0] - c02[0]) * vInt[0] + (cInt[1] - c02[1]) * vInt[1] + (cInt[2] - c02[2]) * vInt[2])
            a = vInt[0] ** 2.0 + vInt[1] ** 2.0 + vInt[2] ** 2.0
            if (b ** 2.0 - 4.0 * a * c) >= 0.0:
                l1 = (-b + (b ** 2.0 - 4.0 * a * c) ** 0.5) / (2.0 * a)
                l2 = (-b - (b ** 2.0 - 4.0 * a * c) ** 0.5) / (2.0 * a)
                f2a = cInt + l1 * vInt
                f2b = cInt + l2 * vInt
            else:
                f2a = np.asarray([np.nan, np.nan, np.nan])
                f2b = np.asarray([np.nan, np.nan, np.nan])

            # midpoint
            xInt = np.asarray([f1a, f1b, f2a, f2b])
            xInt = np.unique(xInt, axis=0)
            slot = len(xInt) - 1
            xMid = []
            for i in range(0, slot + 1):
                if (np.linalg.norm(xInt[slot - i] - c01) >= 1.01 * (dia1)) or (
                        np.linalg.norm(xInt[slot - i] - c02) >= 1.01 * (dia2)) or (np.sum(np.isnan(xInt)) > 0):
                    xInt = np.delete(xInt, (slot - i), axis=0)
            if len(xInt) == 2 and np.sum(np.isnan(xInt)) == 0:
                xMid = 0.5 * (xInt[0] + xInt[1])
            # add pipes to network
            if (np.sum(np.isnan(xInt)) == 0) and len(xInt) == 2:
                # normal fracture-fracture connection
                if (f1_t != typ('boundary')) and (f2_t != typ('boundary')):
                    # source-center to intersection midpoint
                    # add_flowpath(self, source, target, length, width, featTyp, featID):
                    self.add_flowpath(c01,
                                      xMid,
                                      np.linalg.norm(xMid - c01),
                                      np.linalg.norm(xInt[1] - xInt[0]),
                                      f1_t,
                                      sourceID,
                                      Dh=self.faces[sourceID].bh,
                                      Dh_max=self.faces[sourceID].bh,
                                      frict=self.faces[sourceID].roughness)
                    # intersection midpoint to target-center
                    p_1, p_2 = self.add_flowpath(xMid,
                                                 c02,
                                                 np.linalg.norm(xMid - c02),
                                                 np.linalg.norm(xInt[1] - xInt[0]),
                                                 f2_t,
                                                 targetID,
                                                 Dh=self.faces[targetID].bh,
                                                 Dh_max=self.faces[targetID].bh,
                                                 frict=self.faces[targetID].roughness)
                    # store fracture centerpoint node number
                    if p_2 >= 0:
                        self.faces[targetID].ci = p_2

                    # update tracker
                    self.trakr += [[sourceID, targetID]]
                    # fracture-boundary connection (boundary type = -3)
                elif (f2_t == typ('boundary')) and (f1_t != typ('boundary')):
                    # source-center to intersection midpoint
                    self.add_flowpath(c01,
                                      xMid,
                                      np.linalg.norm(xMid - c01),
                                      np.linalg.norm(xInt[1] - xInt[0]),
                                      f1_t,
                                      sourceID,
                                      Dh=self.faces[sourceID].bh,
                                      Dh_max=self.faces[sourceID].bh,
                                      frict=self.faces[sourceID].roughness)
                    # intersection midpoint to far-field
                    p_1, p_2 = self.add_flowpath(xMid,
                                                 self.nodes.r0,
                                                 100.0 * dia2,
                                                 np.linalg.norm(xInt[1] - xInt[0]),
                                                 f2_t,
                                                 targetID,
                                                 Dh=self.faces[targetID].bh,
                                                 Dh_max=self.faces[targetID].bh,
                                                 frict=self.faces[targetID].roughness)
                    # store fracture centerpoint node number
                    if p_2 >= 0:
                        self.faces[targetID].ci = p_2

    # ********************************************************************
    # domain creation
    # ********************************************************************
    def gen_domain(self, plot=True):
        print('*** domain boundaries module ***')
        # clear old data
        self.bound = []
        # working variables
        size = self.rock.size
        # create boundary faces for analysis
        domb3D = []
        domb3D += [Surface(-size, 0.0, 0.0, 4.0 * size, 00.0 * deg, 90.0 * deg, 'boundary', self.rock)]
        domb3D += [Surface(size, 0.0, 0.0, 4.0 * size, 00.0 * deg, 90.0 * deg, 'boundary', self.rock)]
        domb3D += [Surface(0.0, -size, 0.0, 4.0 * size, 90.0 * deg, 90.0 * deg, 'boundary', self.rock)]
        domb3D += [Surface(0.0, size, 0.0, 4.0 * size, 90.0 * deg, 90.0 * deg, 'boundary', self.rock)]
        domb3D += [Surface(0.0, 0.0, -size, 4.0 * size, 00.0 * deg, 00.0 * deg, 'boundary', self.rock)]
        domb3D += [Surface(0.0, 0.0, size, 4.0 * size, 00.0 * deg, 00.0 * deg, 'boundary', self.rock)]
        # add to model domain
        self.bound = domb3D

        # ********************************************************************

    # fracture network creation
    # ********************************************************************
    def gen_fixfrac(self, clear=True,
                    c0=[0.0, 0.0, 0.0],
                    dia=500.0,
                    azn=80.0 * deg,
                    dip=90.0 * deg):
        # print( '-> manual fracture placement module')
        # clear old data
        if clear:
            self.fracs = []

        # place fracture
        c0 = np.asarray(c0)

        # compile list of fractures
        frac3D = [Surface(c0[0], c0[1], c0[2], dia, azn, dip, 'fracture', self.rock)]

        # print( 'dia = %.1f, azn = %.1f, dip = %.1f' %(dia, azn, dip))

        # add to model domain
        self.fracs += frac3D

    # ********************************************************************
    # fracture network creation
    # ********************************************************************
    def gen_natfracs(self, clear=True,
                     f_num=40,
                     f_dia=[200.0, 900.0],
                     f_azn=[79.0 * deg, 8.0 * deg],
                     f_dip=[90.0 * deg, 12.5 * deg]):
        print('-> dfn seed module')
        # clear old data
        if clear:
            self.fracs = []
        # size of domain for reservoir
        size = self.rock.size
        # working variables
        frac3D = []
        # populate fractures
        for n in range(0, f_num):
            # Fracture parameters
            # dia = np.random.uniform(f_dia[0],f_dia[1])
            logmu = 0.5 * (np.log10(f_dia[0]) + np.log10(f_dia[1]))
            dia = lognorm_trunc(1, logmu, logmu, np.log10(f_dia[0]), np.log10(f_dia[1]))[0]  # !!!
            azn = np.random.uniform(f_azn[0], f_azn[1])
            dip = np.random.uniform(f_dip[0], f_dip[1])
            # Build geometry
            x = np.random.uniform(-size, size)
            y = np.random.uniform(-size, size)
            z = np.random.uniform(-size, size)
            c0 = np.asarray([x, y, z])
            # compile list of fractures
            frac3D += [Surface(c0[0], c0[1], c0[2], dia, azn, dip, 'fracture', self.rock)]

        # add to model domain
        self.fracs += frac3D

    # ************************************************************************
    # well placement
    # ************************************************************************
    def gen_joint_sets(self):
        print('*** joint set module ***')
        # clear old joint sets
        self.fracs = []
        # generate fractures from sets
        for i in range(0, len(self.rock.fNum)):
            self.gen_natfracs(False,
                              self.rock.fNum[i],
                              self.rock.fDia[i],
                              self.rock.fStr[i],
                              self.rock.fDip[i])

    # ************************************************************************
    # stimulation - static
    # ************************************************************************
    def gen_stimfracs(self, plot=True,
                      target=0,
                      stages=1,
                      perfs=1,
                      f_dia=[1266.0, 107.0],
                      f_azn=[65.0 * deg, 4.0 * deg],
                      f_dip=[57.5 * deg, 3.75 * deg],
                      clear=True):
        # print( '*** stimulation module ***')
        # clear old data
        if clear == True:
            self.hydfs = []
        # hydraulic fractures
        num = stages * perfs
        # stimulate target well
        spa = self.wells[target].leg / (num + 1)
        c0 = self.wells[target].c0
        azn = self.wells[target].azn
        dip = self.wells[target].dip
        vAxi = np.asarray([math.sin(azn) * math.cos(-dip), math.cos(azn) * math.cos(-dip), math.sin(-dip)])
        for n in range(0, num):
            # Fracture parameters
            leg = np.random.normal(f_dia[0], f_dia[1])
            azn = np.random.normal(f_azn[0], f_azn[1])
            dip = np.random.normal(f_dip[0], f_dip[1])
            c0 = c0 + spa * vAxi

            # add to model domain
            self.hydfs += [Surface(c0[0], c0[1], c0[2], leg, azn, dip, 'propped', self.rock, mcc=self.rock.hfmcc,
                                   phi=self.rock.hfphi)]
            self.hydfs[-1].bd0 = 0.0

    # ************************************************************************
    # well placement
    # ************************************************************************
    def gen_wells(self, clear=True, wells=[]):
        print('*** well placement module ***')
        # clear old data
        if clear:
            self.wells = []
        # manual placement
        if len(wells) > 0:
            self.wells = wells
        # automatic placement
        else:
            # center
            i0 = np.asarray([0.0, 0.0, 0.0])
            # ref axes (parallel injector and 90 horizontal to the right)
            azn = self.rock.w_azimuth
            dip = self.rock.w_dip
            vInj = np.asarray([math.sin(azn) * math.cos(-dip),
                               math.cos(azn) * math.cos(-dip), math.sin(-dip)])
            vRht = np.asarray([math.sin(azn + pi / 2), math.cos(azn + pi / 2), 0.0])
            vNor = np.asarray([math.sin(azn) * math.sin(-dip),
                               math.cos(azn) * math.sin(-dip), math.cos(-dip)])
            # offset center
            p0 = i0 + vRht * self.rock.w_spacing
            # toe in production well
            toe = self.rock.w_toe
            vPro = sg.rotatePoints([vInj], vNor, toe)[0]
            # skew in production well
            skew = self.rock.w_skew
            vPro = sg.rotatePoints([vPro], vRht, skew)[0]
            # phase of production wells
            p0s = []
            vPros = []
            phase = self.rock.w_phase
            num = self.rock.w_count
            for i in range(0, num):
                p0s += [sg.rotatePoints([p0], vInj, (i * 2.0 * pi / num + phase))[0]]
                vPros += [sg.rotatePoints([vPro], vInj, (i * 2.0 * pi / num + phase))[0]]
            # lengths of wells
            length = self.rock.w_length
            proportion = self.rock.w_proportion
            iLen = length * proportion
            pLen = length
            # injection well segments
            i1s = []
            i2s = []
            seg = self.rock.w_intervals
            leg = iLen / (seg + seg - 1)
            i1s += [i0 - 0.5 * vInj * iLen]
            i2s += [i1s[0] + leg * vInj]
            for i in range(1, seg):
                i1s += [i2s[i - 1] + leg * vInj]
                i2s += [i1s[i] + leg * vInj]
            # length of producers
            p1s = []
            p2s = []
            for i in range(0, num):
                p1s += [p0s[i] - 0.5 * vPros[i] * pLen]
                p2s += [p0s[i] + 0.5 * vPros[i] * pLen]
            # place injection wells
            wells = []
            azn, dip = azn_dip(i1s[0], i2s[0])
            for i in range(0, seg):
                wells += [Line(i1s[i][0], i1s[i][1], i1s[i][2], leg, azn, dip, 'injector',
                               self.rock.ra, self.rock.rb, self.rock.rc, self.rock.rgh)]
            # place production wells
            for i in range(0, num):
                azn, dip = azn_dip(p1s[i], p2s[i])
                wells += [Line(p1s[i][0], p1s[i][1], p1s[i][2], pLen, azn, dip, 'producer',
                               self.rock.ra, self.rock.rb, self.rock.rc, self.rock.rgh)]
            # add to model domain
            self.wells = wells

    def add_frac(self, typ='propped',
                 c0=np.asarray([0.0, 0.0, 0.0]),
                 dia=[1266.0, 107.0],
                 azn=[65.0 * deg, 4.0 * deg],
                 dip=[57.5 * deg, 3.75 * deg]):
        """stimulation - add frac"""
        print('   + placing new frac')
        fleg = np.random.normal(dia[0], dia[1])
        fazn = np.random.normal(azn[0], azn[1])
        fdip = np.random.normal(dip[0], dip[1])
        self.hydfs += [Surface(c0[0], c0[1], c0[2], fleg, fazn, fdip, typ, self.rock)]

    # ************************************************************************
    #
    # ************************************************************************
    def gen_pipes(self, plot=True):
        """
        find intersections

        This code segment:
          1. finds intersections & break lines into segments for the flow
          2. builds the input deck for the flow model
          3. be compatible with heat transfer model
          4. not produce duplicate segments
          5. be as efficient as I can muster
          6. reject dead ends if possible
          7. add infinite fracture elements to nodes on boundary
               #re-initialize the geometry - building list of faces
               self.re_init()
        calculate intersections for each well
        """
        #        print( '*** intersections module ***')
        found = False
        for w in range(0, len(self.wells)):
            found += self.x_well_all_faces(sourceID=w)
        if found > 0:
            # chain intersections without repeating same comparitors
            iters = 0
            maxit = 20
            lock = 0
            hold = 0
            while 1:
                # loop breaker
                iters += 1
                if iters > maxit:
                    print(f'-> intersection search stopped after {maxit} iterations')
                    break
                # focus on chain connecting back to wells
                track = np.asarray(self.trakr)
                hold = len(self.trakr)
                conn = True
                # remove duplicate sources
                s_s = track[lock:, 1]
                s_s = np.unique(s_s, axis=0)
                for s in s_s:
                    if s >= 0:
                        # search through all faces
                        for t in range(0, len(self.faces)):
                            # check if already searched
                            ck_1 = np.asarray([np.isin(track[:, 0], t), np.isin(track[:, 1], s)])
                            ck_2 = ck_1[0, :] * ck_1[1, :]
                            ck_3 = np.sum(ck_2)
                            # evaluate if value is valid
                            if (s != t) and (t >= 0) and (ck_3 == 0) and not (
                                    s in track[:, 0]):  # this pair is fresh, check for intersections
                                self.x_frac_face(plot=plot, sourceID=s, targetID=t)
                                conn = False
                        # update tracker
                        self.trakr += [[s, -1]]
                # lockout repeat searches
                lock = hold
                # break if no connections in this search
                if conn:
                    break
            # report number of iterations used to find intersections
            print(f'-> all intersections found using {iters} iters of {maxit} allowable')
        else:
            print('-> wells do not intersect any fractures')

    def get_power(self, detail=False):
        """energy generation - single flash steam rankine cycle"""

        # initialization
        self.Fout = []
        self.Bout = []
        self.Qout = []
        self.Pout = []
        Flash_Power = []
        Binary_Power = []
        Pump_Power = []
        Net_Power = []
        # truncate pressures when superciritical
        i_p = np.max([list(self.i_p) + list(self.p_p)]) / MPa
        if i_p > 100.0:
            i_p = 100.0
        # for each moment in time
        for t in range(0, len(self.p_hm) - 1):
            # Surface Injection Well (5)
            T5 = self.rock.Tinj + 273.15  # K
            P5 = i_p  # MPa
            state = therm(T=T5, P=P5)
            h5 = state.h  # kJ/kg
            s5 = state.s  # kJ/kg-K
            x5 = state.x  # steam quality
            v5 = state.v  # m3/kg

            # Undisturbed Reservoir (r)
            Tr = self.rock.BH_T  # K
            Pr = self.rock.BH_P / MPa  # MPa
            state = therm(T=Tr, P=Pr)
            hr = state.h  # kJ/kg
            sr = state.s  # kJ/kg-K
            xr = state.x  # steam quality
            vr = state.v  # m3/kg

            # Surface Production Well (2)
            P2 = self.rock.p_whp / MPa  # MPa
            h2 = self.p_hm[t]  # kJ/kg
            state = therm(P=P2, h=h2)
            T2 = state.T  # K
            s2 = state.s  # kJ/kg-K
            x2 = state.x  # steam quality
            v2 = state.v  # m3/kg

            # Brine Flow Stream (2l)
            state = therm(P=P2, x=0)
            P2l = state.P  # MPa
            h2l = state.h  # kJ/kg
            T2l = state.T  # K
            s2l = state.s  # kJ/kg-K
            x2l = state.x  # steam quality
            v2l = state.v  # m3/kg

            # turbine with error handling
            P3s = self.rock.AmbPres / MPa
            if x2 > 0.0:
                # Turbine Flow Stream (2s)
                state = therm(P=P2, x=1)
                P2s = state.P  # MPa
                h2s = state.h  # kJ/kg
                T2s = state.T  # K
                s2s = state.s  # kJ/kg-K
                x2s = state.x  # steam quality
                v2s = state.v  # m3/kg

                # Turbine Outflow (3s)
                s3s = s2s
                try:
                    state = therm(P=P3s, s=s3s)
                except NotImplementedError as nie:
                    if P3s < iapws.iapws97.Pmin:
                        # TODO verify that skipping when P3s < iapws97.Pmin is OK/correct
                        print(
                            f'[WARN] Failed to recalculate state for Turbine Outflow (3s) because pressure ({P3s}) '
                            + f'is below IAPWS minimum pressure ({iapws.iapws97.Pmin}). '
                            + 'Skipping recalculation and using existing state.'
                        )
                    else:
                        # Re-raise since we don't know the cause
                        raise nie

                P3s = state.P  # MPa
                h3s = state.h  # kJ/kg
                T3s = state.T  # K
                s3s = state.s  # kJ/kg-K
                x3s = state.x  # steam quality
                v3s = state.v  # m3/kg
            else:
                P2s = state.P  # MPa
                h2s = state.h  # kJ/kg
                T2s = state.T  # K
                s2s = state.s  # kJ/kg-K
                x2s = state.x  # steam quality
                v2s = state.v  # m3/kg

                # Turbine Outflow (3s)
                P3s = state.P  # MPa
                h3s = state.h  # kJ/kg
                T3s = state.T  # K
                s3s = state.s  # kJ/kg-K
                x3s = state.x  # steam quality
                v3s = state.v  # m3/kg

            # Condenser Outflow (4s)
            P4s = P3s
            T4s = T5
            state = therm(T=T4s, P=P4s)
            P4s = state.P  # MPa
            h4s = state.h  # kJ/kg
            T4s = state.T  # K
            s4s = state.s  # kJ/kg-K
            x4s = state.x  # steam quality
            v4s = state.v  # m3/kg

            # Turbine Work
            w3s = h2s - h3s  # kJ/kg

            # Pump Work
            w5s = v5 * (P5 - P4s) * 10 ** 3  # kJ/kg
            w5l = v5 * (P5 - P2l) * 10 ** 3  # kJ/kg

            # efficiency shorthand
            effic = self.rock.GenEfficiency

            # Mass flow rates
            mt = -self.p_mm
            ms = mt * x2
            ml = mt * (1.0 - x2)
            mi = self.i_mm
            Vt = (v5 * mt) * (1000 * 60)  # L/min

            # Pumping power
            Pump = 0.0
            if mi > mt:
                Pump = -1.0 * (ms * w5s + ml * w5l) / effic + -1.0 * (mi - mt) * w5s / effic  # kW
            elif mi < ml:
                Pump = -1.0 * (mi * w5l) / effic  # kW
            else:
                Pump = -1.0 * ((mi - ml) * w5s + ml * w5l) / effic  # kW

            # Flash cycle power
            Flash = 0.0  # kW
            Flash = ms * np.max([0.0, w3s]) * effic  # kW

            # Binary cycle power
            Binary = 0.0

            # Outlet thermal state
            TBo = np.max([T5, 51.85 + 273.15])
            PBo = np.min([P3s, P2])
            state = therm(T=TBo, P=PBo)
            PBo = state.P  # MPa
            hBo = state.h  # kJ/kg
            TBo = state.T  # K

            # Binary Cycle Inlet from Turbine
            TBis = T3s
            PBis = P3s
            hBis = h3s

            # Binary Cycle Inlet from Brine
            TBil = np.min([T2l, T2])
            PBil = P2l
            hBil = np.min([h2l, h2])

            # Binary thermal-electric efficiency
            # (estimated from Heberle and Bruggermann, 2010 - Fig. 4 - doi:10.1016/j.applthermaleng.2010.02.012)
            nBs = np.max([0.0, 0.0899 * TBis - 25.95]) / 100.0
            nBl = np.max([0.0, 0.0899 * TBil - 25.95]) / 100.0
            Binary = (ms * nBs * np.max([0.0, hBis - hBo]) + ml * nBl * np.max(
                [0.0, hBil - hBo])) * effic  # kW, power produced from binary cycle

            # Net power
            Net = 0.0
            Net = Flash + Binary + Pump

            # Record results
            Flash_Power += [Flash]
            Binary_Power += [Binary]
            Pump_Power += [Pump]
            Net_Power += [Net]

        # record results
        self.Fout = np.asarray(Flash_Power)
        self.Bout = np.asarray(Binary_Power)
        self.Qout = np.asarray(Pump_Power)
        self.Pout = np.asarray(Net_Power)

        # print(details)
        if detail:
            print('\n*** Rankine Cycle Thermal State Values ***')
            print(("Inject (5): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T5, P5, h5, s5, x5, v5)))
            print(("Reserv (r,1): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (Tr, Pr, hr, sr, xr, vr)))
            print(("Produc (2): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T2, P2, h2, s2, x2, v2)))
            print(("Turbi (2s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T2s, P2s, h2s, s2s, x2s, v2s)))
            print(("Brine (2l): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T2l, P2l, h2l, s2l, x2l, v2l)))
            print(("Exhau (3s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T3s, P3s, h3s, s3s, x3s, v3s)))
            print(("Conde (4s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T4s, P4s, h4s, s4s, x4s, v4s)))
            print('*** Binary Cycle Thermal State Values ***')
            print(("Steam: Ti= %.2f; Pi= %.2f; hi= %.2f -> To= %.2f, Po= %.2f, ho= %.2f, n =%.3f" % (
                TBis, PBis, hBis, TBo, PBo, hBo, nBs)))
            print(("Brine: Ti= %.2f; Pi= %.2f; hi= %.2f -> To= %.2f, Po= %.2f, ho= %.2f, n =%.3f" % (
                TBil, PBil, hBil, TBo, PBo, hBo, nBl)))
            print('*** Power Output Estimation ***')
            print("Turbine Flow Rate = %.2f kg/s" % (ms))
            print("Bypass Flow Rate = %.2f kg/s" % (ml))
            print("Well Flow Rate = %.2f kg/s = %.2f L/min" % (mt, Vt))
            print("Flash Power at %.2f kW" % (Flash))
            print("Binary Power at %.2f kW" % (Binary))
            print("Pumping Power at %.2f kW" % (Pump))
            print("Net Power at %.2f kW" % (Net))

        #     # Energy production
        #     Pout = 0.0 #kW
        #     # If sufficient steam quality
        #     # if x2 > 0:
        #     #     mt = -self.p_mm
        #     #     ms = mt*x2
        #     #     ml = mt*(1.0-x2)
        #     #     Vt = (v5*mt)*(1000*60) # L/min
        #     #     Pout = ms*wNs*self.rock.GenEfficiency #kW
        #     mt = -self.p_mm
        #     ms = mt*x2
        #     ml = mt*(1.0-x2)
        #     mi = self.i_mm
        #     Vt = (v5*mt)*(1000*60) # L/min
        #     Pout = ms*np.max([0.0, w3s])*self.rock.GenEfficiency #kW, power from flash turbine
        #     Pout += -1.0*(ms*w5s + ml*w5l)/self.rock.GenEfficiency #kW, power consumed by recirculation pumps
        #     Pout += -1.0*(mi-mt)*w5s/self.rock.GenEfficiency #kW, power consumed by makeup water pumps
        #     self.Pout += [Pout]

        #     # Binary Cycle Outlet
        #     TBo = np.max([T5,51.85+273.15])
        #     PBo = np.min([P3s,P2])
        #     state = therm(T=TBo,P=PBo)
        #     PBo = state.P # MPa
        #     hBo = state.h #kJ/kg
        #     TBo = state.T # K
        #     # Binary Cycle Inlet from Turbine
        #     TBis = T3s
        #     PBis = P3s
        #     hBis = h3s
        #     # Binary Cycle Inlet from Brine
        #     TBil = T2l
        #     PBil = P2l
        #     hBil = h2l
        #     # Binary thermal-electric efficiency
        #     nBs = np.max([0.0, 0.0899*TBis - 25.95])/100.0
        #     nBl = np.max([0.0, 0.0899*TBil - 25.95])/100.0
        #     Bout = 0.0 #kW
        #     Bout = ms*np.max([0.0, w3s])*self.rock.GenEfficiency #kW, power from flash turbine
        #     Bout += (ms*nBs*np.max([0.0, hBis-hBo]) + ml*nBl*np.max([0.0, hBil-hBo]))*self.rock.GenEfficiency #kW, power produced from binary cycle
        #     Bout += -1.0*(ms*w5s + ml*w5l)/self.rock.GenEfficiency #kW, power consumed by recirculation pumps
        #     Bout += -1.0*(mi-mt)*w5s/self.rock.GenEfficiency #kW, power consumed by makeup water pumps
        #     self.Bout += [Bout]

        # #print( details)
        # if detail:
        #     print( '\n*** Rankine Cycle Thermal State Values ***')
        #     print( ("Inject (5): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T5,P5,h5,s5,x5,v5)))
        #     print( ("Reserv (r,1): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(Tr,Pr,hr,sr,xr,vr)))
        #     print( ("Produc (2): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T2,P2,h2,s2,x2,v2)))
        #     print( ("Turbi (2s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T2s,P2s,h2s,s2s,x2s,v2s)))
        #     print( ("Brine (2l): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T2l,P2l,h2l,s2l,x2l,v2l)))
        #     print( ("Exhau (3s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T3s,P3s,h3s,s3s,x3s,v3s)))
        #     print( ("Conde (4s): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" %(T4s,P4s,h4s,s4s,x4s,v4s)))
        #     print( '*** Binary Cycle Thermal State Values ***')
        #     print( ("Steam: Ti= %.2f; Pi= %.2f; hi= %.2f -> To= %.2f, Po= %.2f, ho= %.2f, n =%.3f" %(TBis,PBis,hBis,TBo,PBo,hBo,nBs)))
        #     print( ("Brine: Ti= %.2f; Pi= %.2f; hi= %.2f -> To= %.2f, Po= %.2f, ho= %.2f, n =%.3f" %(TBil,PBil,hBil,TBo,PBo,hBo,nBl)))
        #     print( '*** Power Output Estimation ***')
        #     print( ("Turbine Specific Work = %.2f kJ/kg" %(w3s)))
        #     print( ("Turbine Pump Work = %.2f kJ/kg \nBrine Pump Work = %.2f kJ/kg" %(w5s,w5l)))
        #     # print( ("Net Specifc Work Turbine = %.2f kJ/kg" %(wNs)))
        #     print( "Turbine Flow Rate = %.2f kg/s" %(ms))
        #     print( "Bypass Flow Rate = %.2f kg/s" %(ml))
        #     print( "Well Flow Rate = %.2f kg/s" %(mt))
        #     print( "Well Flow Rate = %.2f L/min" %(Vt))
        #     print( "Flash Power at %.2f yr = %.2f kW" %(self.ts[-1]/yr,Pout))
        #     print( "Binary Power at %.2f yr = %.2f kW" %(self.ts[-1]/yr,Bout))


    def get_flow(self, p_bound=0.0 * MPa, q_well=[], p_well=[], reinit=True, useprior=False, Qnom=1.0):
        """flow network model"""
        # reinitialize if the mesh has changed
        if reinit:
            # clear data from prior run
            self.re_init()
            # generate pipes
            self.gen_pipes()

        # set boundary conditions (m3/s) (Pa); 10 kg/s ~ 0.01 m3/s for water
        self.set_bcs(p_bound=p_bound, q_well=q_well, p_well=p_well)

        # get fluid properties
        mu = self.rock.Poremu  # cP
        rho = self.rock.PoreRho  # kg/m3

        # flow solver working variables
        N = self.nodes.num
        Np = self.pipes.num
        H = self.H
        Q = self.Q

        # initial guess for nodal pressure head
        if useprior and not (reinit):
            h = self.nodes.p / (rho * g)
        else:
            # h = 1.0*np.random.rand(N) + p_bound/(rho*g) #!!! older than 2/11/23
            h = (1.0 * MPa / (rho * g)) * np.random.rand(N) + p_bound / (rho * g)
        q = np.zeros(N)

        # install boundary condition
        for i in range(0, len(H)):
            h[H[i][0]] = H[i][1]
        for i in range(0, len(Q)):
            q[Q[i][0]] = Q[i][1]

        # hydraulic resistance equations
        K = np.zeros(Np)
        n = np.zeros(Np)

        # stabilizing limiters
        zlim = 0.3 * self.rock.s3 / (rho * g)
        hup = (self.rock.s1 + 10.0 * MPa) / (rho * g)
        hlo = -101.4 / (rho * g)

        # convergence
        goal = 1.0e-8  # 0.0001

        # dimension limiters for flow solver stability
        self.pipes.Dh_limit(Qnom, goal * rho * g, rho, g, mu, self.rock.kf)

        # hydraulic resistance terms
        for i in range(0, Np):
            # working variables
            u = self.pipes.fID[i]

            # pipes and wells
            if (int(self.pipes.typ[i]) in [typ('injector'), typ('producer'),
                                           typ('pipe')]):  # ((Y[i][2] == 0): #pipe, Hazen-Williams
                self.pipes.Dh[i] = np.min(
                    [self.pipes.Dh_max[i], self.wells[u].ra])  # !!! perhaps better to use self.pipes.W[i]?
                Lscaled = self.pipes.L[i] * mu / (0.9 * cP)
                K[i] = 10.7 * Lscaled / (self.pipes.frict[i] ** 1.852 * self.pipes.Dh[i] ** 4.87)  # metric (m)
                # K[i] = 10.7*self.pipes.L[i]/(self.pipes.frict[i]**1.852*self.pipes.Dh[i]**4.87) #metric (m) #old 2/11/23
                # K[i] = 10.7*self.pipes.L[i]/(self.wells[u].rgh**1.852*self.wells[u].ra**4.87) #metric (m) #oldest
                n[i] = 1.852
            # fractures and planes
            elif (int(self.pipes.typ[i]) in [typ('boundary'), typ('fracture'), typ('propped'),
                                             typ('choke')]):  # (int())Y[i][2] == 1: #fracture, effective cubic law
                self.pipes.Dh[i] = np.min([self.pipes.Dh_max[i], self.faces[u].bh])
                K[i] = (12.0 * mu * self.pipes.L[i]) / (rho * g * self.pipes.W[i] * self.pipes.Dh[i] ** 3.0)
                # K[i] = (12.0*mu*self.pipes.L[i])/(rho*g*self.pipes.W[i]*self.faces[u].bh**3.0)
                n[i] = 1.0
                # porous media
            elif (int(self.pipes.typ[i]) in [typ('darcy')]):
                self.pipes.Dh[i] = np.min([self.pipes.Dh_max[i], self.faces[u].bd])
                K[i] = mu * self.pipes.L[i] / (rho * g * self.pipes.Dh[i] * self.pipes.W[i] * self.rock.kf)
                # K[i] = mu*self.pipes.L[i]/(rho*g*self.faces[u].bd*self.pipes.W[i]*self.rock.Frack)
                n[i] = 1.0
            # type not handled
            else:
                print('error: undefined type of conduit')
                exit()
        # record info
        self.pipes.K = K
        self.pipes.n = n

        # iterative Newton-Rhapson solution to solve flow
        iters = 0
        max_iters = 50
        z = h
        # #add jitters #!!! commented out trying to get low pressure convergence
        # h += 2.0*goal*np.random.rand(N)-goal
        while 1:
            # #debugging #!!!
            # print('... error: %.6e' %(np.max(np.abs(z))))
            # print(h*rho*g)

            # loop breaker
            iters += 1
            if iters > max_iters:
                print('-> Flow solver halted with error of <%.2e m head after %i iterations' % (
                    np.max(np.abs(z)), iters - 1))
                break
            elif (np.max(np.abs(z)) < goal):  # np.max(np.abs(z/(h+z))) < goal:
                print('-> Flow solver converged to <%.2e m head using %i iterations' % (goal, iters - 1))
                break

            # re-initialize working variables
            F = np.zeros(N)
            F += q
            D = np.zeros((N, N))

            # build matrix equations
            for i in range(0, Np):
                # working variables
                n0 = self.pipes.n0[i]
                n1 = self.pipes.n1[i]

                # Node flow equations
                R = np.sign(h[n0] - h[n1]) * (abs((h[n0] - h[n1])) / K[i]) ** (1.0 / n[i])
                F[n0] += R
                F[n1] += -R

                # Jacobian (first derivative of the inflow-outflow equations)
                if abs((h[n0] - h[n1])) == 0:
                    J = 1.0
                else:
                    J = ((1.0 / n[i]) / K[i]) * (abs((h[n0] - h[n1])) / K[i]) ** (1.0 / n[i] - 1.0)
                D[n0, n0] += J
                D[n1, n1] += J
                D[n0, n1] += -J
                D[n1, n0] += -J

            # remove defined boundary values
            for i in range(0, len(H)):
                F = np.delete(F, H[-1 - i][0], 0)
                D = np.delete(D, H[-1 - i][0], 0)
                D = np.delete(D, H[-1 - i][0], 1)

            # solve matrix equations
            z = solve(D[:, :], F[:])

            # #apply correction limiters to prevent excess overshoot
            # z[z > zlim] = zlim
            # z[z < -zlim] = -zlim

            # update pressures
            for i in range(0, len(H)):
                z = np.insert(z, H[i][0], 0, axis=0)
            h = h - 0.9 * z  # 0.7 scaling factor seems to give faster convergence by reducing solver overshoot

            # apply physical limits
            h[h > hup] = hup
            h[h < hlo] = hlo

        # flow rates
        q = np.zeros(Np)
        for i in range(0, Np):
            # working variables
            n0 = self.pipes.n0[i]
            n1 = self.pipes.n1[i]
            # flow rate
            q[i] = np.sign(h[n0] - h[n1]) * (abs(h[n0] - h[n1]) / K[i]) ** (1.0 / n[i])

        # record results in class
        self.nodes.p = h * rho * g
        self.q = q

        # collect well rates and pressures
        i_q = []
        i_p = []
        p_q = np.zeros(len(self.wells), dtype=float)
        p_p = np.zeros(len(self.wells), dtype=float)

        for w in range(0, len(self.wells)):
            # coordinates
            source = self.wells[w].c0
            # find index of duplicate
            ck, i = self.nodes.add(source)
            # record pressure
            p_p[w] = self.nodes.p[i]
            # record flow rate
            i_pipe = np.where(np.asarray(self.pipes.n0) == i)[0][0]
            p_q[w] = self.q[i_pipe]

        # collect boundary rates and pressures
        b_nodes = [0]
        b_pipes = []
        b_q = []
        b_p = []
        w = b_nodes[0]
        b_pipes = np.where(np.asarray(self.pipes.n1) == w)[0]
        b_p += [self.nodes.p[w]]
        if len(b_pipes) > 0:
            for w in b_pipes:
                b_q += [-self.q[w]]
        b_p = list(np.ones(len(b_q), dtype=float) * b_p[0])

        # store key well and boundary flow data
        self.i_p = i_p
        self.i_q = i_q
        self.p_p = p_p
        self.p_q = p_q
        self.b_p = b_p
        self.b_q = b_q

    def get_heat(self, plot=True,
                 t_n=-1,  # steps
                 t_f=-1.0 * yr,  # s
                 H=-1.0,  # kW/m2-K
                 dT0=-666.6,  # K
                 dE0=-666.6,  # kJ/m2
                 detail=False,
                 lapse=False):
        """
        heat transfer model
        - mod 1-28-2021: correct errors
        - mod 9-13-2022: reduce overshoot in initial timesteps
        """
        print('*** heat flow module ***')
        # ****** default parameters ******
        if t_n < 0:
            t_n = self.rock.TimeSteps
        if t_f < 0:
            t_f = self.rock.LifeSpan
        if H < 0:
            H = self.rock.H_ConvCoef
        if dT0 < -666.0:
            dT0 = self.rock.dT0
        if dE0 < -666.0:
            dE0 = self.rock.dE0

        # ****** boundary parameters ******
        # truncate pressures when supercritical
        i_p = np.max([list(self.i_p) + list(self.p_p)]) / MPa
        if i_p > 100.0:
            i_p = 100.0
            # Surface Injection Well (5)
        T5 = self.rock.Tinj + 273.15  # K
        P5 = i_p  # MPa
        state = therm(T=T5, P=P5)
        h5 = state.h  # kJ/kg
        s5 = state.s  # kJ/kg-K
        x5 = state.x  # steam quality
        v5 = state.v  # m3/kg
        self.v5 = v5
        print(("Inject (5): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (T5, P5, h5, s5, x5, v5)))
        # Undisturbed Reservoir (r)
        Tr = self.rock.BH_T  # K
        Pr = self.rock.BH_P / MPa  # MPa
        state = therm(T=Tr, P=Pr)
        hr = state.h  # kJ/kg
        sr = state.s  # kJ/kg-K
        xr = state.x  # steam quality
        vr = state.v  # m3/kg
        print(("Reserv (r): T= %.2f; P= %.2f; h= %.2f, s= %.4f, x= %.4f, v= %.6f" % (Tr, Pr, hr, sr, xr, vr)))

        # ****** enthalpy function linearization *******
        if xr > 0.0001:
            print('warning: reservoir water is mixed phase (x = %.3f) so solver will be unreliable' % (xr))
        x = np.linspace(T5, Tr, 100, dtype=float)
        y = np.zeros(100, dtype=float)
        for i in range(0, len(x)):
            y[i] = therm(T=x[i], P=Pr).h  # kJ/kg
        hTP = np.polyfit(x, y, 3)
        ThP = np.polyfit(y, x, 3)
        ##error checking
        # y2 = hTP[0]*x**3.0 + hTP[1]*x**2.0 + hTP[2]*x**1.0 + hTP[3]
        # x2 = ThP[0]*y**3.0 + ThP[1]*y**2.0 + ThP[2]*y**1.0 + ThP[3]
        # fig = pylab.figure(figsize=(8.0, 6.0), dpi=96, facecolor='w', edgecolor='k',tight_layout=True) # Medium resolution
        # ax1 = fig.add_subplot(111)
        # ax1.plot(x,y,label='raw')
        # ax1.plot(x,y2,label='fitted')
        # ax1.plot(x2,y,label='reverse')
        # ax1.set_ylabel('Enthalpy (kJ/kg)')
        # ax1.set_xlabel('Temperature (K)')
        # ax1.legend(loc='upper left', prop={'size':8}, ncol=2, numpoints=1)

        # ****** explicit solver setup ******
        # working variables
        ts = np.linspace(0.0, t_f, t_n + 1)
        dt = ts[1] - ts[0]
        # set boundary conditions #K
        self.therm_bcs(T_bound=Tr,
                       T_inlet=[T5])
        # set solver parameters
        N = self.nodes.num
        Np = self.pipes.num
        Tb = self.Tb
        #        Y = self.pipes
        # initial guess for temperatures #!!!
        Tn = np.ones(N) * (Tr - dT0)  # K
        # Tn = np.ones(N) * Tr #K
        # node pressures from flow solution
        Pn = np.asarray(self.nodes.p) / MPa  # MPa
        # truncate high pressures for solver stability (supercritical states)
        Pn[Pn > 100.0] = 100.0
        # install boundary condition
        for i in range(0, len(Tb)):
            Tn[Tb[i][0]] = Tb[i][1]

        # more working variables
        Lp = np.asarray(self.pipes.L)
        ms = np.asarray(self.q) / v5  # assume density of fluid as injection fluid density at wellhead
        hn = np.zeros(N)
        R0 = np.zeros(Np)  # ones(len(Y))*2.0*BoreOR #initialize 'thermal radius' to 2x radius of borehole
        ResSv = self.rock.ResSv
        ResKt = self.rock.ResKt
        CemKt = self.rock.CemKt

        # memory working variables
        ht = np.zeros((t_n + 1, N), dtype=float)
        Tt = np.zeros((t_n + 1, N), dtype=float)
        Rt = np.zeros((t_n + 1, Np), dtype=float)
        Et = np.zeros((t_n + 1, Np), dtype=float)
        Qt = np.zeros((t_n + 1, Np), dtype=float)
        Er = np.zeros(Np, dtype=float)

        # well geometry #@@@@@@@ need to update for a per-borehole basis
        Ris = self.rock.ra
        Ric = self.rock.rb
        Rir = self.rock.rc

        # functional form of energy vs thermal radius for specified borehole diameter (per unit DT and dL)
        Ror = np.linspace(1, 2000, 2000)  # (BoreOR,200,100)
        ERor = 2 * pi * ResSv * 1.0 * ((1 - np.log(Rir) / np.log(Rir / Ror)) * (Ror ** 2 - Rir ** 2) / 2
                                       + (1 / (2 * np.log(Rir / Ror))) * (
                                               Ror ** 2 * (np.log(Ror) - 0.5) - Rir ** 2 * (np.log(Rir) - 0.5)))
        lnRor = np.log(Ror[:])
        lnERor = np.log(ERor[:])
        ERm, ERb, r_value, p_value, std_err = stats.linregress(lnERor,
                                                               lnRor)  # E[j] = np.exp((np.log(Ror)-ERb)/ERm)*dL*(Tor-T[j]) # kJ

        # key indecies for convergence criteria (i.e., boundary nodes)
        key = []
        for e in self.H:
            key += [e[0]]
            key += [e[0] + 1]
        for e in self.Q:
            key += [e[0]]
            key += [e[0] + 1]

        # convergence criteria
        goal = 0.5
        goalE = 0.03

        # iterate over time
        for t in range(0, len(ts) - 1):  # !!! add self-estimation of dE0 for stabilization
            # calculate nodal temperatures by pipe flow and nodal mixing
            iters = 0
            err = np.ones(N) * goal * 10
            E0_update_intervals = 5
            max_iters = 30 * E0_update_intervals
            E0e = np.zeros(Np) + Et[0, :]
            dE0e = np.zeros(Np)

            # iterate for temperature stability
            while 1:
                # calculate nodal fluid enthalpy #@@@ requires consideration of sensible heating (0<X<1) if not supercritical
                hn = hTP[0] * Tn ** 3.0 + hTP[1] * Tn ** 2.0 + hTP[2] * Tn ** 1.0 + hTP[3]
                # temperature convergence
                kerr = np.max(np.abs(err))
                # energy convergence
                eerr = np.max(np.abs(dE0e) / (np.abs(E0e) + 1.0e-9))
                # loop breaker
                iters += 1
                if iters > max_iters:
                    print('Heat solver halted after %i iterations' % (iters - 1))
                    break
                elif (kerr < goal) and (eerr < goalE):  # np.max(np.abs(err)) < goal:
                    print('Heat solver converged to %e Kelvin after %i iterations' % (goal, iters - 1))
                    break
                # follow the flow to estimate heating/cooling of fluid per pipe
                Ap = np.zeros(Np, dtype=float)
                Bp = np.zeros(Np, dtype=float)
                Cp = np.zeros(Np, dtype=float)
                Dp = np.zeros(Np, dtype=float)
                Ep = np.zeros(Np, dtype=float)
                hm = np.zeros(N, dtype=float)
                mi = np.zeros(N, dtype=float)
                for p in range(0, Np):
                    # working variables
                    n0 = self.pipes.n0[p]
                    n1 = self.pipes.n1[p]
                    # get overshoot limit for timestep for each pipe #!!! edit 9-13-2022 start
                    if (iters - 1) % E0_update_intervals == 0:
                        dT = 0.5 * (Tn[n1] + Tn[n0]) - Tr
                        dT = np.max([np.abs(dT0), np.abs(dT)])
                        a = 1.0 / (self.rock.ResSv * np.abs(dT) * self.rock.ResKt * 10 ** -3)
                        b = 1.0 / self.rock.H_ConvCoef
                        c = -2.0 * np.abs(dT) * dt
                        dE0 = (-b + (b ** 2.0 - 4.0 * a * c) ** 0.5) / (2.0 * a)
                        # get extracted energy - Et, thermal radius - R0, heat flow rate - Qt
                        if (int(self.pipes.typ[p]) in [typ('injector'), typ('producer'),
                                                       typ('pipe')]):  # pipe, radial heat flow
                            # energy withdraw
                            E0p = dE0 * 2.0 * pi * Rir * Lp[p]  # kJ
                            Esp = Et[t, p]
                            Etp = np.max([E0p, Esp])
                            dE0e[p] = Etp - E0e[p]
                            E0e[p] = Etp
                            # initial rock thermal radius
                            R0[p] = np.exp(ERm * (np.log(np.abs(Etp / (Lp[p] * dT)))) + ERb) + Rir  # m
                            # initial rock energy transfer rates
                            Qt[t, p] = Lp[p] / (1.0 / (2.0 * pi * Ris * H) + np.log(R0[p] / Rir) / (
                                    2.0 * pi * ResKt * 10 ** -3) + np.log(Rir / Ric) / (
                                                        2.0 * pi * CemKt * 10 ** -3))  # kJ/K-s
                        elif (int(self.pipes.typ[p]) in [typ('boundary'), typ('fracture'), typ('propped'), typ('darcy'),
                                                         typ('choke')]):  # fracture, plate heat flow
                            # rock energy withdraw
                            E0p = dE0 * self.pipes.W[p] * Lp[p]  # kJ
                            Esp = Et[t, p]
                            Etp = np.max([E0p, Esp])
                            dE0e[p] = Etp - E0e[p]
                            E0e[p] = Etp
                            # rock thermal radius
                            R0[p] = Etp / (ResSv * self.pipes.W[p] * Lp[p] * dT)  # m
                            # rock energy transfer rates
                            Qt[t, p] = (2.0 * self.pipes.W[p] * Lp[p]) / (
                                    1.0 / (H) + R0[p] / (ResKt * 10 ** -3))  # kJ/K-s
                        else:
                            print('error: segment type %s not identified' % (
                                typ(int(self.pipes.typ[p]))))  # !!! edit 9-13-2022 end

                    # equilibrium enthalpy
                    heq0 = hTP[0] * Tr ** 3.0 + hTP[1] * Tr ** 2.0 + hTP[2] * Tr ** 1.0 + hTP[3]
                    heq1 = heq0

                    # working variables
                    Kp = 0.0
                    Qp = 0.0

                    # positive flow
                    if ms[p] > 0:
                        # non-equilibrium conduction limited heating
                        Ap[p] = Qt[t, p] * (Tr - 0.5 * (Tn[n1] + Tn[n0]))
                        # equilibrium conduction limited heating
                        Bp[p] = Qt[t, p] * (Tr - 0.5 * (Tr + Tn[n0]))
                        # flow limited cooling to equilibrium
                        Cp[p] = ms[p] * (heq1 - hn[n0])
                        # flow limited cooling to non-equilibrium
                        Dp[p] = ms[p] * (hn[n1] - hn[n0])

                    # negative flow
                    else:
                        # non-equilibrium conduction limited heating
                        Ap[p] = Qt[t, p] * (Tr - 0.5 * (Tn[n0] + Tn[n1]))
                        # equilibrium conduction limited heating
                        Bp[p] = Qt[t, p] * (Tr - 0.5 * (Tr + Tn[n1]))
                        # flow limited cooling to equilibrium
                        Cp[p] = -ms[p] * (heq0 - hn[n1])
                        # flow limited cooling to non-equilibrium
                        Dp[p] = -ms[p] * (hn[n0] - hn[n1])

                    # take maximum of conduction terms because this will drive conduction heat deliverability
                    Kp = np.asarray([Ap[p], Bp[p]])[np.argmax(np.abs([Ap[p], Bp[p]]))]
                    # if flow limits heat extraction from rock, it will go to equilibrium
                    Qp = Cp[p]
                    # get the limiting term
                    KorQ = np.argmin(np.abs([Kp, Qp]))
                    Ep[p] = np.asarray([Kp, Qp])[np.argmin(np.abs([Kp, Qp]))]

                    # conduction limited
                    if KorQ == 0:
                        # positive flow
                        if ms[p] > 0:
                            mi[n1] += ms[p]
                            hm[n1] += Ep[p] + ms[p] * hn[n0]
                        # negative flow
                        else:
                            mi[n0] += -ms[p]
                            hm[n0] += Ep[p] + -ms[p] * hn[n1]
                    # flow limited
                    else:
                        # positive flow
                        if ms[p] > 0:
                            mi[n1] += ms[p]
                            hm[n1] += ms[p] * heq1
                        # negative flow
                        else:
                            mi[n0] += -ms[p]
                            hm[n0] += -ms[p] * heq0

                # calculate nodal temperatures
                z = []
                z = np.zeros(N, dtype=float)  # -0.0001*np.random.rand(N) + Tr #K
                hu = np.zeros(N, dtype=float)
                for n in range(0, N):
                    # mixed inflow enthalpy
                    if mi[n] > 0:
                        hu[n] = hm[n] / mi[n]
                    else:
                        hu[n] = hr
                    # calculate temperature at new enthalpy
                    #                    z[n] = therm(h=hu[n],P=Pn[n]).T
                    z[n] = ThP[0] * hu[n] ** 3.0 + ThP[1] * hu[n] ** 2.0 + ThP[2] * hu[n] ** 1.0 + ThP[3]

                # install boundary condition
                for j in range(0, len(Tb)):
                    z[Tb[j][0]] = Tb[j][1]
                    #                    hu[Tb[j][0]] = therm(T=z[Tb[j][0]],P=Pn[Tb[j][0]]).h
                    hu[Tb[j][0]] = hTP[0] * z[Tb[j][0]] ** 3.0 + hTP[1] * z[Tb[j][0]] ** 2.0 + hTP[2] * z[
                        Tb[j][0]] ** 1.0 + hTP[3]

                # calculate error
                err = []  # np.zeros(N,dtype=float)
                err = Tn - z

                # update Tn
                Tn = z

            # store ht
            ht[t] = hu
            # store temperatures
            Tt[t, :] = Tn
            # store thermal radii
            Rt[t, :] = R0

            # timelapse 3D
            if lapse:
                self.nodes.T = Tn
                self.nodes.h = hn
                self.build_vtk(fname='t%02d' % (t))

            # extracted energy during this time step
            Et[t + 1] = Et[t] + np.abs(Ep) * dt
            # rock energy tracker (added or lost)
            Er += Ep * dt
            for i in range(0, Np):
                # working variables
                n0 = self.pipes.n0[i]
                n1 = self.pipes.n1[i]
                dT = abs(Tr - 0.5 * (Tn[n1] + Tn[n0]))

                # @@@@ stabilizer
                dT = np.max([dT, dT0])

                # thermal radius for next time step
                if (int(self.pipes.typ[i]) in [typ('injector'), typ('producer'),
                                               typ('pipe')]):  # pipe, radial heat flow
                    if (dT > 0) and (Et[t + 1, i] > 0):
                        R0[i] = np.exp(ERm * (np.log(np.abs(Et[t + 1, i] / (Lp[i] * dT)))) + ERb) + Rir  # +2.0*Rir # m
                    # Et[0,i] = np.exp((np.log(R0[i])-ERb)/ERm)*Lp[i]*(Tr-0.5*(Tn[Y[i][1]]+Tn[Y[i][0]])) # kJ
                    Qt[t + 1, i] = Lp[i] / (1.0 / (2.0 * pi * Ris * H) + np.log(R0[i] / Rir) / (
                            2.0 * pi * ResKt * 10 ** -3) + np.log(Rir / Ric) / (
                                                    2.0 * pi * CemKt * 10 ** -3))  # kJ/K-s # Note converted Kt in W/m-K to kW/m-K

                elif (int(self.pipes.typ[i]) in [typ('boundary'), typ('fracture'), typ('propped'), typ('darcy'),
                                                 typ('choke')]):  # fracture, plate heat flow
                    if (dT > 0) and (Et[t + 1, i] > 0):
                        R0[i] = Et[t + 1, i] / (ResSv * self.pipes.W[i] * Lp[i] * dT)
                    # Et[0,i] = ResSv*R0[i]*Y[i][4]*Lp[i]*(Tr-0.5*(Tn[Y[i][1]]+Tn[Y[i][0]])) # kJ
                    Qt[t + 1, i] = (2.0 * self.pipes.W[i] * Lp[i]) / (
                            1.0 / (H) + R0[i] / (ResKt * 10 ** -3))  # kJ/K-s # Note converted Kt in W/m-K to kW/m-K
                else:
                    print('error: segment type %s not identified' % (typ(int(self.pipes.typ[i]))))

        # store results
        self.Et = Et
        self.Qt = Qt
        self.nodes.T = Tn
        self.nodes.h = hn
        self.ms = ms
        self.Tt = Tt
        self.ht = ht
        self.R0 = R0
        self.Rt = Rt

        # parameters of interest
        # **********************
        # collect well temp, rate, enthalpy
        w_h = []
        w_T = []
        w_m = []
        for w in range(0, len(self.wells)):
            # coordinates
            source = self.wells[w].c0
            # find index of duplicate
            ck, i = self.nodes.add(source)
            # record temperature
            w_T += [Tt[:, i]]
            # record enthalpy
            w_h += [ht[:, i]]
            # record mass flow rate
            i_pipe = np.where(np.asarray(self.pipes.n0) == i)[0][0]
            w_m += [self.q[i_pipe] / v5]
        w_h = np.asarray(w_h)
        w_T = np.asarray(w_T)
        w_m = np.asarray(w_m)

        # identify injectors and producers
        iPro = np.where(w_m <= 0.0)[0]
        iInj = np.where(w_m > 0.0)[0]

        # boundary flows
        b_nodes = [0]
        b_pipes = []
        b_h = []
        b_T = []
        b_m = []
        w = b_nodes[0]
        b_pipes = np.where(np.asarray(self.pipes.n1) == w)[0]
        b_h += [ht[:, w]]
        b_T += [Tt[:, w]]
        if len(b_pipes) > 0:
            for w in b_pipes:
                b_m += [self.q[w] / v5]

        # total production energy
        p_ET = 0.0
        for i in iPro:
            i = int(i)
            p_ET += np.sum(w_m[i] * w_h[i])  # kJ/s
        p_ET = p_ET * dt / t_f  # /len(p_h[w]) #kJ/s avg over all

        # mixed produced enthalpy and mass flow rate
        p_mm = []
        p_hm = np.zeros(len(ts))
        p_mm = 0.0
        for i in iPro:
            i = int(i)
            p_mm += w_m[i]
            p_hm += w_h[i] * w_m[i]
        if p_mm < 0:
            p_hm = p_hm / p_mm
        else:
            p_hm = np.ones(len(ts)) * hr
        self.p_mm = p_mm  # mixed produced mass flow rate
        self.p_hm = p_hm  # mixed produced enthalpy

        # total injection energy
        i_ET = 0.0
        for i in iInj:
            i = int(i)
            i_ET += np.sum(w_m[i] * w_h[i])  # kJ/s
        i_ET = i_ET * dt / t_f  # /len(i_h[w])

        # mixed injection mass flow rate
        i_mm = []
        i_mm = 0.0
        for i in iInj:
            i = int(i)
            i_mm += w_m[i]
        self.i_mm = i_mm  # mixed produced mass flow rate

        # total boundary energy flow
        b_ET_out = 0.0
        b_ET_in = 0.0
        b_ET = 0.0
        b_ni = 0
        b_no = 0
        if len(b_pipes) > 0:
            for w in range(0, len(b_pipes)):
                # outflow
                if b_m[w] > 0:
                    b_ET_out += -np.sum(b_m[w] * b_h[0])
                    b_no += 1
                # inflow
                else:
                    b_ET_in += -np.sum(b_m[w] * b_h[0])
                    b_ni += 1
            if b_no > 0:
                b_ET_out = b_ET_out * dt / t_f  # /b_no
            if b_ni > 0:
                b_ET_in = b_ET_in * dt / t_f  # /b_ni
            b_ET = b_ET_out + b_ET_in

        # rock energy for thermal radius
        # E_tot = (np.sum(Et[-1,:]) - np.sum(Et[0,:]))/t_f #kJ/s

        # rock energy change
        E_roc = np.sum(Er) / t_f  # kJ/s

        # net system energy (less error in model if closer to zero)
        E_net = E_roc + p_ET + i_ET + b_ET  # kJ/s
        print('\nNet System Energy (kJ/s):')
        print(E_net)

        # save key values
        self.ts = ts
        self.w_h = w_h
        self.w_m = w_m
        self.b_h = b_h
        self.b_m = b_m

        # calculate power output
        self.get_power(detail=detail)

        # thermal energy extraction
        dht = np.zeros(len(ts), dtype=float)
        for i in range(0, len(w_m)):
            dht += -w_m[i] * w_h[i]
        self.dhout = dht

        if plot:  # plots
            fig = pylab.figure(figsize=(11.0, 8.5), dpi=96, facecolor='w', edgecolor='k',
                               tight_layout=True)  # Medium resolution
            font = {'family': 'serif', 'size': 16}
            pylab.rc('font', serif='Arial')
            pylab.rc('font', **font)
            ax1 = fig.add_subplot(221)
            for i in iPro:
                i = int(i)
                ax1.plot(ts[:-1] / yr, w_h[i][:-1], linewidth=1.5)
            ax1.set_xlabel('Time (yr)')
            ax1.set_ylabel('Production Enthalpy (kJ/kg)')
            # ax1.set_ylim(bottom=0.0)
            ax2 = fig.add_subplot(222)
            ax2.plot(ts[:-1] / yr, self.Fout[:], linewidth=1.0, color='red')
            ax2.plot(ts[:-1] / yr, self.Bout[:], linewidth=1.0, color='blue')
            ax2.plot(ts[:-1] / yr, self.Qout[:], linewidth=1.0, color='cyan')
            ax2.plot(ts[:-1] / yr, self.Pout[:], linewidth=1.5, color='black')
            ax2.set_xlabel('Time (yr)')
            ax2.set_ylabel('Fla-R, Bin-B, Pum-C, Net-K (kWe)')
            # ax2.set_ylim(bottom=0.0)
            ax3 = fig.add_subplot(223)
            for i in iPro:
                i = int(i)
                ax3.plot(ts[:-1] / yr, w_T[i][:-1], linewidth=1.5)
            ax3.set_xlabel('Time (yr)')
            ax3.set_ylabel('Production Temperature (K)')
            # ax3.set_ylim(bottom=273.0)
            #            ax3.plot(ts/yr,np.sum(Et,axis=1),linewidth=0.5,color='black')
            #            ax3.set_xlabel('Time (yr)')
            #            ax3.set_ylabel('Rock Energy (kJ)')
            ax4 = fig.add_subplot(224)
            ax4.plot(ts[:-1] / yr, dht[:-1], linewidth=1.5, color='green')
            ax4.set_xlabel('Time (yr)')
            ax4.set_ylabel('Thermal Extraction (kJ/s)')
            # ax4.set_ylim(bottom=0.0)

    def dyn_stim(
            self,
            Vinj=-1.0,
            Qinj=-1.0,
            dpp=-666.6 * MPa,
            sand=-1.0,
            leakoff=-1.0,
            target=0,
            perfs=-1,
            r_perf=-1.0,
            visuals=True,
            fname='stim',
            pfinal_max=999.9 * MPa):
        """
        stimulation - add frac

        Parameters
        ----------
        Vinj -- total volume per stage, sand ratio to frac slurry by volume
        """

        print('*** dynamic stim module ***')

        # fetch defaults
        if perfs < 0:
            perfs = self.rock.perf
        if r_perf < 0:
            r_perf = self.rock.r_perf
        if sand < 0:
            sand = self.rock.sand
        if leakoff < 0:
            leakoff = self.rock.leakoff
        if dpp < -666.0 * MPa:
            dpp = self.rock.dPp
        if Vinj < 0:
            Vinj = self.rock.Vinj
        if Qinj < 0:
            Qinj = self.rock.Qinj
        if pfinal_max > 999.0 * MPa:
            pfinal_max = self.rock.pfinal_max
        Qinj

        # user status update
        print(
            '+> dynamic stimulation with injection volume (Vinj) = %.1e m3 and rate (Qinj) = %.3e m3/s' % (Vinj, Qinj))

        # bottom hole pressure, reservoir pore pressure
        bhp = self.rock.BH_P  # Pa
        # production well pressure
        pwp = bhp + dpp  # Pa

        # get index of injection and production wells (index will match p_q and i_q from flow solver outputs)
        i_div = 0
        i_key = []
        p_div = 0
        p_key = []
        for i in range(0, len(self.wells)):
            if int(self.wells[i].typ) in [typ('injector')]:
                i_key += [int(i)]
                i_div += 1
            if int(self.wells[i].typ) in [typ('producer')]:
                p_key += [int(i)]
                p_div += 1
        i_key = np.asarray(i_key, dtype=int)
        p_key = np.asarray(p_key, dtype=int)

        # initialize targets for stimulation
        if not target:
            target = i_key
        else:
            pass

        # looping variables
        vol_ini = 0.0  # m3
        vol_new = 0.0  # m3
        vol_old = 0.0  # m3
        vol_rem = np.ones(i_div, dtype=float) * Vinj  # m3
        Pis = []  # Pa
        Qis = []  # m3/s
        completed = np.zeros(i_div, dtype=bool)  # T/F segment stim complete
        # hydrofrac = np.zeros(i_div,dtype=bool) #T/F hydrofrac instability detection
        stabilize = np.zeros(i_div, dtype=bool)  # T/F detection of stable flow
        tip = np.ones(i_div, dtype=float) * bhp  # trial injection pressure
        dpi = np.ones(i_div, dtype=float) * -self.rock.dPi  # trial pressure

        # #check if injectors were already hydrofraced #!!!
        # for i in range(0,i_div):
        #     hydrofrac[i] = self.wells[i_key[i]].hydrofrac

        # if target is specified
        if target.any():
            for i in range(0, i_div):
                # match targets to i_key
                if not (i_key[i] in list(target)):
                    completed[i] = True

        # initial fracture parameters and network volume
        self.re_init()
        for i in range(0, len(self.faces)):
            # correct for critically weak fractures
            self.faces[i].check_integrity(rock=self.rock, pres=(self.rock.BH_P + 0.5 * self.rock.dPi))
            # time variable properties
            self.faces[i].Pmax = bhp
            self.faces[i].Pcen = bhp
            # self.GR_bh(i)
            self.hydromech(i)
            if typ(self.faces[i].typ) != 'boundary':
                vol_ini += (4.0 / 3.0) * pi * 0.25 * self.faces[i].dia ** 2.0 * 0.5 * self.faces[i].bd
        vol_old = vol_ini

        # stimulation loop
        if visuals:
            Rs = []
            ts = []
            Ps = []
            ws = []
            Vs = []
            Pn = []

        iters = 0
        maxit = 40
        while 1:
            # loop breaker
            if iters >= maxit:
                print(f'-> rock stimulation halted at {iters} iterations')
                break
            iters += 1
            print(f'\n[{iters}] rock stimulation step')

            # get test injection pressures
            for i in range(0, i_div):
                # set to boundary pressure if interval was completed
                if completed[i]:
                    tip[i] = bhp
                # set with pressure incrementer if not completed
                else:
                    tip[i] = self.rock.s3 + dpi[i]

            # boundary condition placeholders
            q_well = np.full(len(self.wells), None)
            p_well = np.full(len(self.wells), None)

            # set injection boundary conditions
            for i in range(0, i_div):
                p_well[i_key[i]] = tip[i]

            # set production boundary conditions
            for i in range(0, p_div):
                p_well[p_key[i]] = pwp

            # solve flow with pressure drive
            self.get_flow(p_bound=bhp, p_well=p_well, q_well=q_well, Qnom=Qinj)

            # fetch pressure and flow rates
            Pis += [tip]
            Qi = []
            for i in range(0, i_div):
                Qi += [self.p_q[i_key[i]]]
            Qis += [Qi]

            # create vtk
            if visuals:
                fname2 = f'{fname}_A_{iters}'
                self.build_vtk(fname2, vtype=[0, 0, 1, 1, 1, 0])

            # stimulation complete if pressure driven injection rate exceeds stimulation injection rate in all wells
            # i_q, p_q, b_q are + for flow into the frac network
            for i in range(0, i_div):
                if Qi[i] > Qinj:
                    completed[i] = True
                    # stabilize[i] = True #!!!

            # break if all are completed
            if np.sum(completed) == i_div:
                print('-> stimulation complete: full flow achieved')
                break

            # get max pressure on each fracture from all the nodes associated with that fracture
            face_pmax = np.ones(len(self.faces), dtype=float) * bhp
            for i in range(0, self.pipes.num):
                if (int(self.pipes.typ[i]) in [typ('boundary'), typ('fracture'), typ('propped'),
                                               typ('choke')]):  # don't confuse well ID with face ID
                    face_pmax[self.pipes.fID[i]] = np.max(
                        [face_pmax[self.pipes.fID[i]], self.nodes.p[self.pipes.n0[i]], self.nodes.p[self.pipes.n1[i]]])
            # update fracture properties; stimulate fractures; grow fractures; calculate new fracture volume
            if visuals:
                R = []
                w = []
                V = []
                P = []
            nat_stim = False
            vol_new = 0.0
            num_stim = 0
            for i in range(0, len(self.faces)):
                # record maximum and center node pressures
                self.faces[i].Pmax = face_pmax[i]
                self.faces[i].Pcen = self.nodes.p[self.faces[i].ci]
                # compute fracture properties, if stimulated acknowledge it
                # nat_stim += self.GR_bh(i)
                nat_stim += self.hydromech(i)
                # calculate new fracture volume
                if typ(self.faces[i].typ) != 'boundary':
                    vol_new += (4.0 / 3.0) * pi * 0.25 * self.faces[i].dia ** 2.0 * 0.5 * self.faces[i].bd
                # get maximum number of stimulations
                num_stim = np.max([self.faces[i].stim, num_stim])

                # #identify if fracture is hydroprop
                # if self.faces[i].hydroprop:
                #     #hydrofrac = True
                #     for j in range(0,i_div):
                #         #only record for intervals that are hydropropped
                #         if not(completed[j]):
                #             hydrofrac[j] = True
                #             self.wells[i_key[j]].hydrofrac = True

                # variable tracking for visuals
                if visuals:
                    R += [0.5 * self.faces[i].dia]
                    w += [self.faces[i].bd]
                    V += [(4.0 / 3.0) * pi * 0.25 * self.faces[i].dia ** 2.0 * 0.5 * self.faces[i].bd]
                    P += [self.faces[i].Pcen]

            if visuals:
                Rs += [R]
                ws += [w]
                Vs += [V]
                Pn += [P]

            # remaining injection volume for stimulation accounting for leakoff volume
            if visuals:
                t = []
                P = []

            for i in range(0, i_div):
                # only modify stimulations if stage is not yet completed
                if not (completed[i]):
                    # calculate volume change before next fracture in chain will be triggered
                    time_step = (vol_new - vol_old) / (Qinj - Qi[i])
                    vol_rem[i] = vol_rem[i] - time_step * Qinj
                    print('   - (%i) volume remaining %.3e m3' % (i, vol_rem[i]))

                    # stage complete if target volume is reached
                    if vol_rem[i] < 0.0:
                        print(f'   $ ({i}) completed by reaching target injection volume')
                        completed[i] = True

                    # stimulate hydraulic fractures if criteria met
                    # if (nat_stim == False) and (tip > self.rock.s3+0.1*MPa) and (hydrofrac == False): #and (np.max(self.p_p) < 0.0):
                    elif (self.wells[i_key[i]].hydrofrac == False) and (tip[i] > (self.rock.s3 + self.rock.hfmcc)):
                        print(f'   ! ({i}) hydraulic fractures')
                        # hydrofrac[i] = True
                        self.wells[i_key[i]].hydrofrac = True  # !!!
                        # seed hydraulic fracture
                        self.gen_stimfracs(target=i_key[i],
                                           perfs=perfs,
                                           f_dia=[2.0 * r_perf, 0.0],
                                           f_azn=[self.rock.s3Azn + np.pi / 2.0, self.rock.s3AznVar],
                                           f_dip=[np.pi / 2.0 - self.rock.s3Dip, self.rock.s3DipVar],
                                           clear=False)
                        for notch in range(0, perfs):
                            # print('stim integrity check %i: pres = %.3e, tip = %.3e' %(len(self.faces)+perfs-notch-1,(self.rock.s3 + self.rock.hfmcc),tip[i]))
                            fi = len(self.hydfs) - notch - 1
                            si = self.hydfs[fi].sn
                            # self.hydfs[len(self.hydfs)-notch-1].make_critical(rock=self.rock,pres=(tip[i]-0.5*self.rock.dPi)) #!!! check uses injection pressure
                            self.hydfs[fi].make_critical(rock=self.rock, pres=(si + self.rock.hfmcc))
                    # if insufficient pressure and insufficient rate or too many repeated stimulations,
                    # increase pressure
                    elif ((nat_stim == False) or (((int(num_stim) + 1) % int(self.rock.stim_limit)) == 0)):
                        dpi[i] += self.rock.dPi
                        print('   + (%i) pressure increased to %.3f, %.3f absolute' % (
                            i, self.rock.s3 + dpi[i], tip[i] + dpi[i]))
                    if visuals:
                        t += [time_step]
                        P += [tip[i]]

            # update fracture network volume
            vol_old = vol_new

            # visuals
            if visuals:
                ts += [t]
                Ps += [P]

        # @@@
        print('\n[B] Final flow solve')

        # ***** reset pressures and fracture geometry
        for i in range(0, len(self.faces)):
            self.faces[i].Pmax = bhp
            self.faces[i].Pcen = bhp
            # self.GR_bh(i,fix=True)
            self.hydromech(i, fix=True)

        # ***** final pressure calculation to set facture apertures
        print('1: Pressure boundary conditions with stimulation disabled -> get fracture apertures')
        # fixed pressure solve
        q_well = np.full(len(self.wells), None)
        p_well = np.full(len(self.wells), None)
        # set injection boundary conditions using maximum values
        for i in range(0, i_div):
            tip[i] = self.rock.s3 + dpi[i]
            # limit pressure if commanded to do so
            if tip[i] > pfinal_max:
                tip[i] = pfinal_max
            p_well[i_key[i]] = tip[i]
        # set production boundary conditions
        for i in range(0, p_div):
            p_well[p_key[i]] = pwp

        # solve flow
        self.get_flow(p_bound=bhp, p_well=p_well, q_well=q_well, reinit=False, Qnom=Qinj)
        if visuals:
            fname2 = fname + '_B1'
            self.build_vtk(fname2, vtype=[0, 0, 1, 1, 1, 0])

            # get max pressure on each fracture from all the nodes associated with that fracture
        face_pmax = np.ones(len(self.faces), dtype=float) * bhp
        for i in range(0, self.pipes.num):
            if (int(self.pipes.typ[i]) in [typ('boundary'), typ('fracture'), typ('propped'),
                                           typ('choke')]):  # don't confuse well ID with face ID
                face_pmax[self.pipes.fID[i]] = np.max(
                    [face_pmax[self.pipes.fID[i]], self.nodes.p[self.pipes.n0[i]], self.nodes.p[self.pipes.n1[i]]])
        # update fracture properties without stimualtion
        for i in range(0, len(self.faces)):
            # record maximum and center node pressures
            self.faces[i].Pmax = face_pmax[i]
            self.faces[i].Pcen = self.nodes.p[self.faces[i].ci]
            # compute fracture properties
            # self.GR_bh(i,fix=True)
            self.hydromech(i, fix=True)

        # ***** flag unstable hydropropped scenarios
        # ... if any fractures connected to the injector are hydropropped, stabilization is required
        # search by pipes (chokes give fracture id, connectors give well id)
        for j in range(0, self.pipes.num):
            # find the choke elements
            if self.pipes.typ[j] == typ('choke'):
                # get the well information
                fID = self.pipes.fID[j]
                wID = self.pipes.fID[j - 1]
                Qii = self.p_q[wID]
                if (self.wells[wID].typ == typ('injector')):  # or (self.wells[wID].typ == typ('producer')):
                    if (self.faces[fID].hydroprop):
                        stabilize[wID] = True

        # ***** flow rate solve for heat transfer solution
        print('2: Flow boundary conditions with stimulation disabled -> get flow in network')
        q_well = np.full(len(self.wells), None)
        p_well = np.full(len(self.wells), None)
        # set injection boundary conditions using flow values, unless stable flow was never acheived (e.g., hydrofrac only)
        for i in range(0, i_div):
            Qii = self.p_q[i_key[i]]
            if (stabilize[i]) or (Qii > Qinj):
                q_well[i_key[i]] = Qinj
            else:
                p_well[i_key[i]] = tip[i]
        # set production boundary conditions
        for i in range(0, p_div):
            p_well[p_key[i]] = pwp

        # solve flow
        self.get_flow(p_bound=bhp, p_well=p_well, q_well=q_well, reinit=False, useprior=True, Qnom=Qinj)

        # ***** solver overrides for key inputs and outputs
        Pi = []
        Qi = []
        for i in range(0, i_div):
            # locate injection node
            source = self.wells[i_key[i]].c0
            ck, j = self.nodes.add(source)
            # bad solution if injection pressures are excessive
            if self.nodes.p[j] > 1.05 * tip[i]:
                print('** ERROR: Pressures are excessive so final flow is invalid')
            elif stabilize[i]:
                self.nodes.p[j] = tip[i]
                Pi += [tip[i]]
            else:
                Pi += [self.nodes.p[j]]
            Qi += [self.p_q[i_key[i]]]
        Pis += [Pi]
        Qis += [Qi]

        # final visualization
        # Qis = np.asarray(Qis)
        # Pis = np.asarray(Pis)
        if visuals:
            # create vtk with final flow data
            fname2 = f'{fname}_B2'
            self.build_vtk(fname2)
            self.v_Rs = Rs
            self.v_ts = ts
            self.v_Ps = Ps
            self.v_ws = ws
            self.v_Vs = Vs
            self.v_Pn = Pn

    # ************************************************************************
    # stimulation & flow
    # ************************************************************************
    def stim_and_flow(self, Vstim=-1.0, Qstim=-1.0,
                      Vinj=-1.0, Qinj=-1.0, dpp=-666.6 * MPa,
                      sand=-1.0, leakoff=-1.0,
                      target=0, perfs=-1, r_perf=-1.0,
                      clear=True, visuals=True, fname='stim'):
        # fetch defaults
        if perfs < 0:
            perfs = self.rock.perf
        if r_perf < 0:
            r_perf = self.rock.r_perf
        if sand < 0:
            sand = self.rock.sand
        if leakoff < 0:
            leakoff = self.rock.leakoff
        if dpp < -666.0 * MPa:
            dpp = self.rock.dPp
        if Vinj < 0:
            Vinj = self.rock.Vinj
        if Qinj < 0:
            Qinj = self.rock.Qinj
        if Vstim < 0:
            Vstim = self.rock.Vstim
        if Qstim < 0:
            Qstim = self.rock.Qstim

        # Solve stimulation
        self.dyn_stim(Vinj=Vstim, Qinj=Qstim, target=target,
                      visuals=visuals, fname=(fname + '_stim'))

        # Solve production
        self.dyn_stim(Vinj=Vinj, Qinj=Qinj, target=target,
                      visuals=visuals, fname=(fname + '_prod'))

    # ************************************************************************
    # stimulation & flow
    # ************************************************************************
    def dyn_flow(self,
                 Vinj=-1.0, Qinj=-1.0, dpp=-666.6 * MPa,
                 sand=-1.0, leakoff=-1.0,
                 target=0, perfs=-1, r_perf=-1.0,
                 clear=True, visuals=True, fname='stim'):
        # fetch defaults
        if perfs < 0:
            perfs = self.rock.perf
        if r_perf < 0:
            r_perf = self.rock.r_perf
        if sand < 0:
            sand = self.rock.sand
        if leakoff < 0:
            leakoff = self.rock.leakoff
        if dpp < -666.0 * MPa:
            dpp = self.rock.dPp
        if Vinj < 0:
            Vinj = self.rock.Vinj
        if Qinj < 0:
            Qinj = self.rock.Qinj

        # Solve production
        self.dyn_stim(Vinj=Vinj, Qinj=Qinj, target=target,
                      visuals=visuals, fname=(fname + '_prod'))

    # ************************************************************************
    # basic validation of fracture geometry
    # ************************************************************************
    def detournay_visc(self, Q0=0.08):
        # plot initialization
        fig = pylab.figure(figsize=(15.0, 8.5), dpi=96, facecolor='w', edgecolor='k',
                           tight_layout=True)  # Medium resolution
        font = {'family': 'serif', 'size': 16}
        pylab.rc('font', serif='Arial')
        pylab.rc('font', **font)
        ax1 = fig.add_subplot(231)
        ax2 = fig.add_subplot(232)
        ax3 = fig.add_subplot(234)
        ax4 = fig.add_subplot(235)
        ax5 = fig.add_subplot(236)

        # normalized constants
        E_prime = self.rock.ResE / (1.0 - self.rock.Resv ** 2.0)
        K_prime = 4.0 * self.rock.Kic * (2.0 / pi) ** 0.5
        mu_prime = 12.0 * self.rock.Poremu

        # time
        time = np.linspace(1000.0, 200000.0, 100, dtype=float)
        rho = np.linspace(0.001, 0.999, 100, dtype=float)
        drho = rho[1] - rho[0]
        wst = []
        pst = []
        rst = []
        Vt = []
        Pt = []

        for t in time:
            # radius
            sca_radi = 0.0
            sca_Kscas = []
            sca_apers = []
            sca_press = []
            for p in range(0, len(rho)):
                # viscosity dominated if K_scaled < 1.0
                K_scaled = K_prime * (t ** 2.0 / (mu_prime ** 5.0 * Q0 ** 3.0 * E_prime ** 13.0)) ** (1.0 / 18.0)

                # scaled aperture (ohmega_bar_m0) and scaled pressure (pi_m0)
                scaled_aper = (((0.6846 * 70.0 ** 0.5) / 3.0 + (13.0 * rho[p] - 6.0) * (
                        0.07098 * 4.0 * 5.0 ** 0.5) / 9.0) * (1.0 - rho[p]) ** (2.0 / 3.0) +
                               0.09269 * ((1.0 - rho[p]) ** 0.5 * 8.0 / pi - np.arccos(rho[p]) * rho[p] * 8.0 / pi))
                scaled_pres = 0.3581 * (2.479 - 2.0 / (3.0 * (1.0 - rho[p]) ** (1.0 / 3.0))) - 0.09269 * (
                        np.log(rho[p] / 2.0) + 1.0)

                sca_Kscas += [K_scaled]
                sca_apers += [scaled_aper]
                sca_press += [scaled_pres]

                # scaled radius (gamma_m0)
                if p != 0:
                    sca_radi += 0.5 * (scaled_aper + sca_apers[p - 1]) * 0.5 * (rho[p] + rho[p - 1]) * drho
            sca_radi = (2.0 * pi * sca_radi) ** (-1.0 / 3.0)

            # convert to arrays for math
            sca_Kscas = np.asarray(sca_Kscas)
            sca_apers = np.asarray(sca_apers)
            sca_press = np.asarray(sca_press)

            # less scaled aperture (ohmega_m0)
            n_apers = sca_apers * sca_radi

            # lets now undo this irritating scaling crap
            Lm = (E_prime * Q0 ** 3.0 * t ** 4.0 / mu_prime) ** (1.0 / 9.0)
            em = (mu_prime / (E_prime * t)) ** (1.0 / 3.0)
            ws = em * Lm * n_apers
            ps = em * E_prime * sca_press
            rs = Lm * rho * sca_radi
            dr = Lm * drho * sca_radi

            # store for plotting
            wst += [ws]
            pst += [ps]
            rst += [rs]

            # now for what we actually care about: volume and radius
            vol = 0.0
            pnet = 0.0
            for i in range(1, len(rs)):
                vol += 2.0 * pi * (0.5 * (rs[i - 1] + rs[i])) * (0.5 * (ws[i - 1] + ws[i])) * dr
                pnet += 2.0 * pi * (0.5 * (rs[i - 1] + rs[i])) * (0.5 * (ps[i - 1] + ps[i])) * dr
            pnet = pnet / (pi * rs[-1] ** 2.0)
            Vt += [vol]
            Pt += [pnet]

            # plot
            ax1.plot(rs, ps)
            ax2.plot(rs, ws)
        # ax3.plot(time,np.asarray(Vt))
        # ax4.plot(time,np.asarray(Pt))
        Vt = np.asarray(Vt)
        Pt = np.asarray(Pt)
        rst = np.asarray(rst)
        ax3.plot(rst[:, -1], Vt)
        ax4.plot(rst[:, -1], Pt)
        ax5.plot(rst[:, -1], Vt / (pi * rst[:, -1] ** 2.0))

        # labels
        ax1.set_xlabel('Radial Distance (m)')
        ax1.set_ylabel('Pressure (Pa)')

        ax2.set_xlabel('Radial Distance (m)')
        ax2.set_ylabel('Aperture (m)')

        ax3.set_xlabel('Radius (m)')
        ax3.set_ylabel('Volume (m3)')

        ax4.set_xlabel('Radius (m)')
        ax4.set_ylabel('Avg. Net Pressure (Pa)')

        ax5.set_xlabel('Radius (m)')
        ax5.set_ylabel('Avg. Aperture (m)')

    # ************************************************************************
    # optimization objective function (with $!!!), to be normalized to 2021 studies
    # ************************************************************************
    def get_economics(self,
                      interest=0.04,  # standard inflation rate, 4% rule
                      sales_kWh=0.1372,  # $/kWh - customer electricity retail price
                      drill_m=2763.06,  # $/m - Lowry et al, 2017 large diameter well baseline
                      pad_fixed=590e3,  # $ Lowry et al, 2017 large diameter well baseline
                      plant_kWe=2025.65,  # $/kWe simplified from GETEM model
                      explore_m=2683.41,  # $/m simplified from GETEM model
                      oper_kWh=0.03648,  # $/kWh simplified from GETEM model
                      quake_coef=2e-4,
                      # $/Mw for $300M Mw 5.5 quake Pohang (Westaway, 2021) & $17.2B Mw 6.3 quake Christchurch (Swiss Re)
                      quake_exp=5.0,
                      # $/Mw for $300M Mw 5.5 quake Pohang (Westaway, 2021) & $17.2B Mw 6.3 quake Christchurch (Swiss Re)
                      detail=False,  # print cycle infomation
                      plots=False):  # plot results
        # eliminate periods of negative net power production
        Pout_NN = self.Pout + 0.0
        Pout_NN[Pout_NN < 0.0] = 0.0
        NPsum = np.sum(Pout_NN)
        # get system values
        dt = (self.ts[1] - self.ts[0]) / yr
        life = self.rock.LifeSpan / yr
        depth = self.rock.ResDepth
        lateral = (self.rock.w_length * self.rock.w_count) + (self.rock.w_proportion * self.rock.w_length)
        drill_len = self.rock.ResDepth * (self.rock.w_count + 1) + lateral
        Max_Quake = -10.0
        for i in range(0, len(self.faces)):
            if self.faces[i].Mws:
                Max_Quake = np.max([Max_Quake, np.max(self.faces[i].Mws)])
        # NPsum = np.sum(self.Pout[:])
        # power profit
        P = (sales_kWh - oper_kWh) * NPsum * dt * 24.0 * 365.2425
        # capital costs
        C = 0.0
        C += drill_m * drill_len
        C += pad_fixed
        C += plant_kWe * NPsum * dt / life
        C += explore_m * depth
        # quake cost
        Q = quake_coef * np.exp(Max_Quake * quake_exp)
        # net present value
        NPV = P - C - Q
        # detail
        if detail:
            print('\n*** economics module ***')
            print('   sales: $%.0f (%.2f kWh)' % (P, NPsum * dt * 24.0 * 365.2425))
            print('   capital: $%.0f (%.2f m drilled length)' % (C, drill_len))
            print('   seismic: $%.0f (%.2f Mw max quake)' % (Q, Max_Quake))
            print('   NPV: $%.0f' % (NPV))

        self.NPV = NPV
        return NPV, P, C, Q


# ****************************************************************************
#### main program
# ****************************************************************************
if __name__ == '__main__':  # main program
    # create mesh object (the model)
    #    mnode = []
    #    mpipe = []
    #    mfrac = []
    #    mwell = []
    #    mhydf = []
    #    mboun = []
    #    mfrac = np.asarray(mfrac)
    #    geo = [None,None,None,None,None] #[natfracs, origin, intlines, points, wells]
    #    geo[0]=sg.mergeObj(geo[0], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0.1,0,0]), r=0.1))
    #    geo[1]=sg.mergeObj(geo[1], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([20,0,0]), r=3.0))
    #    geo[1]=sg.mergeObj(geo[1], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0,20,0]), r=3.0))
    #    geo[1]=sg.mergeObj(geo[1], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0,0,20]), r=3.0))
    #    geo[2]=sg.mergeObj(geo[2], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0.1,0,0]), r=0.1))
    #    geo[3]=sg.mergeObj(geo[3], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0.1,0,0]), r=0.1))
    #    geo[4]=sg.mergeObj(geo[3], sg.cylObj(x0=np.asarray([0,0,0]), x1=np.asarray([0.1,0,0]), r=0.1))
    geom = Mesh()  # node=mnode,pipe=mpipe,fracs=mfrac,wells=mwell,hydfs=mhydf,bound=mboun,geo3D=geo)

    # generate the domain
    geom.gen_domain()
    # >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
    # modify reservoir parameters as needed
    geom.rock.size = 800.0  # m
    geom.rock.ResDepth = 6000.0  # m
    geom.rock.ResGradient = 50.0  # 56.70 # C/km; average = 25 C/km
    geom.rock.LifeSpan = 20.0  # Years
    geom.rock.CasingIR = 0.0254 * 3.0  # m
    geom.rock.CasingOR = 0.0254 * 3.5  # m
    geom.rock.BoreOR = 0.0254 * 4.0  # m
    geom.rock.PoreRho = 960.0  # kg/m3 starting guess
    geom.rock.Poremu = 0.9 * cP  # Pa-s
    geom.rock.Porek = 0.1 * mD  # m2
    # <<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<

    # generate natural fractures
    geom.gen_natfracs(f_num=40,
                      f_dia=[300.0, 1200.0],
                      f_azn=[79.0 * deg, 8.0 * deg],  # [0.0*deg,3000.0*deg],#[79.0*deg,8.0*deg],
                      f_dip=[90.0 * deg, 12.5 * deg])  # [90.0*deg,0.1*deg])#,12.5*deg])

    # vary well spacing with N-S oriented wells
    spacing = [400.0]  # [100.0,200.0,300.0,400.0,500.0,600.0,700.0,800.0] #,300.0,400.0]
    w_r_Es = []
    w_i_Ps = []
    w_P_os = []
    w_p_hs = []
    w_p_ms = []
    first = True
    for s in range(0, len(spacing)):
        # generate wells
        wells = []
        # wells += [line(0.0+0.5*spacing[s],-300.0,0.0,600.0,0.0*deg,0.0*deg,'injector',0.2286,80.0)]
        # wells += [line(0.0-0.5*spacing[s],-300.0,0.0,600.0,0.0*deg,0.0*deg,'producer',0.2286,80.0)]
        wells += [Line(0.0 - 1.0 * spacing[s], -300.0, 0.0, 600.0, 0.0 * deg, 0.0 * deg, 'producer', 0.2286, 80.0)]
        wells += [Line(0.0 + 0.0 * spacing[s], -300.0, 0.0, 600.0, 0.0 * deg, 0.0 * deg, 'injector', 0.2286, 80.0)]
        wells += [Line(0.0 + 1.0 * spacing[s], -300.0, 0.0, 600.0, 0.0 * deg, 0.0 * deg, 'producer', 0.2286, 80.0)]
        #        #injection well
        #        wells += [well(300.0,-200.0,0.0, 600.0, 324.0*deg, 0.0*deg,-1,0.2286,80.0)]
        #        #production well
        #        wells += [well(000.0,-400.0,0.0, 600.0, 324.0*deg, 0.0*deg,-2,0.2286,80.0)]
        geom.gen_wells(wells)

        # generate fractures
        geom.gen_stimfracs(target=1, perfs=2)

        # re-initialize the geometry - building list of faces
        geom.re_init()

        # populate fracture properties
        if first:
            first = False
            geom.static_KQn()

        # generate pipes
        geom.gen_pipes(plot=first)

        # test different flowrates
        flows = [
            -0.040]  # [-0.001,-0.005,-0.010,-0.015,-0.020,-0.025,-0.030,-0.035,-0.040,-0.045,-0.050,-0.055,-0.060,-0.065]
        dpps = [-2.0 * MPa]
        p_hs = []
        p_ms = []
        p_Es = []
        p_hms = []
        p_mms = []
        i_Ps = []
        i_ms = []
        b_hs = []
        b_ms = []
        b_Es = []
        r_Es = []
        P_os = []

        # calculate suitable production pressure
        h_bh = geom.rock.BH_P / (geom.rock.PoreRho * g)  # m
        dpps = h_bh - np.asarray(dpps) / (geom.rock.PoreRho * g)  # m

        for f in flows:
            # set boundary conditions (m3/s) (Pa); 10 kg/s ~ 0.01 m3/s for water
            geom.set_bcs(plot=False,
                         p_bound=h_bh,
                         q_inlet=[f],
                         p_outlet=[dpps, dpps])

            # calculate flow
            geom.get_flow()

            # claculate heat transfer
            geom.get_heat(plot=False, t_n=21)
            p_hs += [geom.p_h]
            p_ms += [geom.p_m]
            p_hms += [geom.p_hm]
            p_mms += [geom.p_mm]
            #            p_Es += [geom.p_E]
            i_Ps += [geom.i_p]
            i_ms += [geom.i_m]
            b_hs += [geom.b_h]
            b_ms += [geom.b_m]
            #            b_Es += [geom.b_E]
            r_Es += [np.sum(geom.Et, axis=1)]
            P_os += [geom.Pout]

            #        #calculate power output
            #        geom.get_power(detail=False)
            #        P_os += [geom.Pout]

            # visualization
            fname = 'flow%.3f_spacing%.1f_well%i' % (-f, spacing[s], len(wells))
            geom.build_vtk(fname)

        # array format
        p_hs = np.asarray(p_hs)
        p_ms = np.asarray(p_ms)
        p_hms = np.asarray(p_hms)
        p_mms = np.asarray(p_mms)
        #        p_Es = np.asarray(p_Es)
        i_Ps = np.asarray(i_Ps)
        i_ms = np.asarray(i_ms)
        b_hs = np.asarray(b_hs)
        b_ms = np.asarray(b_ms)
        #        b_Es = np.asarray(b_Es)
        r_Es = np.asarray(r_Es)
        P_os = np.asarray(P_os)

        # store values for fancy plotting
        w_r_Es = [r_Es]
        w_i_Ps = [i_Ps]
        w_P_os = [P_os]
        w_p_hs = [p_hs]
        w_p_ms = [p_ms]

        # plot key variables
        if True:
            fig = pylab.figure(figsize=(8.0, 6.0), dpi=96, facecolor='w', edgecolor='k',
                               tight_layout=True)  # Medium resolution

            # mean production enthalpy
            ax1 = fig.add_subplot(221)
            for x in range(0, len(flows)):
                lab = '%.3f m3/s' % (flows[x])
                p_hm = p_hms[x]
                ax1.plot(geom.ts[:-1] / yr, p_hm[:-1], linewidth=0.5, label=lab)
            ax1.set_xlabel('Time (yr)')
            ax1.set_ylabel('Production Enthalpy (kJ/kg)')
            # ax1.legend(loc='upper right', prop={'size':8}, ncol=1, numpoints=1)

            # mean production energy
            ax2 = fig.add_subplot(222)
            for x in range(0, len(flows)):
                lab = '%.3f m3/s' % (flows[x])
                ax2.plot(geom.ts[:-1] / yr, P_os[x][:], linewidth=0.5, label=lab)
            ax2.set_xlabel('Time (yr)')
            ax2.set_ylabel('Production Energy (kJ/s)')
            # ax2.legend(loc='upper right', prop={'size':8}, ncol=1, numpoints=1)

            # max injection pressure
            ax3 = fig.add_subplot(223)
            i_pm = []
            for x in range(0, len(flows)):
                np.asarray(i_Ps)
                i_pm += [np.max(i_Ps[x, :]) / MPa]
            ax3.plot(-np.asarray(flows), i_pm, '-', linewidth=0.5)
            ax3.set_xlabel('Injection Rate (m3/s)')
            ax3.set_ylabel('Injection Pressure (MPa)')
            # ax3.legend(loc='upper right', prop={'size':8}, ncol=1, numpoints=1)

            # total rock energy
            ax4 = fig.add_subplot(224)
            for x in range(0, len(flows)):
                lab = '%.3f m3/s' % (flows[x])
                ax4.plot(geom.ts / yr, r_Es[x], linewidth=0.5, label=lab)
            ax4.set_xlabel('Time (yr)')
            ax4.set_ylabel('Rock Energy (kJ)')
            ax4.legend(loc='upper left', prop={'size': 8}, ncol=2, numpoints=1)

            # per well performance
            NP = np.shape(p_hs)[1]
            for x in range(0, len(flows)):
                fig = pylab.figure(figsize=(8.0, 3.5), dpi=96, facecolor='w', edgecolor='k',
                                   tight_layout=True)  # Medium resolution
                # production enthalpy
                ax1 = fig.add_subplot(121)
                for y in range(0, NP):
                    lab = 'P%i' % (y)
                    ax1.plot(geom.ts[:-1] / yr, p_hs[x, y, :-1], linewidth=0.5, label=lab)
                lab = 'Pnet'
                ax1.plot(geom.ts[:-1] / yr, p_hms[x, :-1], linewidth=1.0, label=lab)
                ax1.set_xlabel('Time (yr)')
                ax1.set_ylabel('Production Enthalpy (kg/kJ)')
                tit = 'Flow at %.3f m3/s' % (flows[x])
                ax1.set_title(tit)

                # production energy
                ax2 = fig.add_subplot(122)
                for y in range(0, NP):
                    lab = 'P%i' % (y)
                    ax1.plot(geom.ts[:-1] / yr, p_hs[x, y, :-1], linewidth=0.5, label=lab)
                lab = 'Pnet'
                ax2.plot(geom.ts[:-1] / yr, p_hms[x, :-1], linewidth=1.0, label=lab)
                tit = 'Flow at %.3f m3/s' % (flows[x])
                ax2.set_title(tit)

    pylab.show()

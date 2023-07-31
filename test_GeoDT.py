import unittest
from pathlib import Path

import numpy as np
import pylab

from GeoDT import mesh


class GeoDTTest(unittest.TestCase):

    def output_path(self, file_name, output_dir='build'):
        return str(Path(output_dir, file_name))

    def test_geodt(self):
        # ****************************************************************************
        #### test program (i.e. script development)
        # ****************************************************************************
        geom = mesh()
        #    geom.rock.s3Azn = 0.0*deg
        #    geom.rock.s3Dip = 0.0*deg
        #    phi = 30.0*deg
        #    mcc = 0.0*MPa
        #    stress = cauchy()
        #    stress.set_sigG_from_Principal(geom.rock.s3, geom.rock.s2, geom.rock.s1, geom.rock.s3Azn, geom.rock.s3Dip)
        #    stress.plot_Pc(phi,mcc)
        #    print('Pc for frac')
        #    print(stress.Pc_frac(90.0*deg,90.0*deg,phi,mcc))

        # generate domain
        geom.gen_domain()

        #    #generate natural fractures
        #    geom.gen_natfracs(f_num=8,
        #                      f_dia = [1200.0,2400.0],
        #                      f_azn = [79.0*deg,8.0*deg], #[0.0*deg,3000.0*deg],#[79.0*deg,8.0*deg],
        #                      f_dip = [90.0*deg,12.5*deg]) #[90.0*deg,0.1*deg])#,12.5*deg])
        #    #generate natural fractures
        #    geom.gen_natfracs(f_num=80,
        #                      f_dia = [300.0,900.0],
        #                      f_azn = [79.0*deg,8.0*deg], #[0.0*deg,3000.0*deg],#[79.0*deg,8.0*deg],
        #                      f_dip = [90.0*deg,12.5*deg]) #[90.0*deg,0.1*deg])#,12.5*deg])

        # generate natural fractures
        geom.gen_joint_sets()

        # generate wells
        wells = []
        #    wells += [line(0.0-1.0*100.0,-300.0,0.0,600.0,0.0*deg,0.0*deg,'producer',0.2286,80.0)]
        #    wells += [line(0.0+0.0*100.0,-300.0,0.0,600.0,0.0*deg,0.0*deg,'injector',0.2286,80.0)]
        #    wells += [line(0.0+1.0*100.0,-300.0,0.0,600.0,0.0*deg,0.0*deg,'producer',0.2286,80.0)]
        geom.gen_wells(True, wells)

        #    #generate hydraulic fracture
        ##    geom.dyn_stim(Vinj=100000.0,Qinj=0.08,dpp=-2.0*MPa,sand=0.3,leakoff=0.0,
        ##                  target=1,clear=True,visuals=False,fname='stim')
        #    geom.dyn_stim(Vinj=100000.0,Qinj=0.08,
        #                  target=1,clear=True,visuals=False,fname='stim')
        #
        #    #calculate normal flow
        #    geom.dyn_stim(Vinj=12614400.0,Qinj=0.02,
        #                  target=1,clear=False,visuals=False,fname='stim')

        # calculate injection and production after stimulation
        #    for i in range(0,len(geom.wells)):
        #        if (int(geom.wells[i].typ) in [typ('injector')]):
        #            target = int(i)
        #            geom.stim_and_flow(target=i,visuals=False,fname='run')
        # random identifier (statistically should be unique)
        pin = np.random.randint(100000000, 999999999, 1)[0]

        geom.stim_and_flow(target=[], visuals=True, fname=self.output_path(f'run_{pin}'))

        # calculate heat transfer
        geom.get_heat(plot=True)

        # show flow model
        geom.build_vtk(fname=self.output_path(f'fin_{pin}'))
        #    geom.rock.stress.plot_Pc(geom.rock.phi[1],geom.rock.mcc[1])

        # save primary inputs and outputs
        x = geom.save(self.output_path('inputs_results.txt'), pin)

        # show plots
        pylab.show(block=False)

        #    #calculate flow
        #    bhp = geom.rock.BH_P #Pa
        #    dpp=-2.0*MPa
        #    pwp = bhp + dpp #Pa
        #    geom.get_flow(p_bound=bhp,q_inlet=[0.02],p_outlet=[pwp])
        #
        #    #build result vtk
        #    geom.build_vtk('fin')

        #    #calculate flow
        #    geom.get_flow()
        #        #standard fluid density
        #        rho = self.rock.PoreRho #kg/m3
        #        #bottom hole pressure, reservoir pore pressure
        #        bhp = self.rock.BH_P #Pa
        #        #production well pressure
        #        pwp = bhp + dpp #Pa
        #        #trial injection pressure
        #        tip = self.rock.s3 + 6.0*MPa #Pa
        #        #stim volume
        #        vol = 0.0 #m3
        #
        #        #looping variables
        #        iters = 0
        #        maxit = 1
        #        while 1:
        #            #***   loop breaker   ***
        #            if iters >= maxit:
        #                break
        #            iters += 1
        #            print '-> rock stimulation step %i' %(iters)
        #
        #            #***   pressure based stimulation   ***
        #            #solve flow with max pressure drive
        #            self.get_flow(p_bound=bhp,p_inlet=[tip],p_outlet=[pwp])

        #    #initialize model
        #    geom.re_init()
        #
        #    #base parameter assignments
        #    geom.static_KQn()
        #
        #    #geom.gen_domain()
        #    geom.build_vtk('test')


if __name__ == '__main__':
    unittest.main()

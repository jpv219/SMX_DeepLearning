### SMX_Automation_simulation_run, tailored for BLUE 12.5.1
### HPC scheduling and monitoring script
### to be run in the HPC node
### Author: Juan Pablo Valdes,
### First commit: July, 2023
### Department of Chemical Engineering, Imperial College London

import os
from subprocess import Popen, PIPE
from time import sleep
import pandas as pd
import shutil
import glob
import math
import datetime
import subprocess
import re
import argparse
import json
import numpy as np


######################## EXCEPTION CLASSES ######################

class JobStatError(Exception):
    """Exception class for qstat exception when job has finished or has been removed from HPC run queue"""
    def __init__(self, message="Output empty on qstat execution, job finished or removed"):
        self.message = message
        super().__init__(self.message)

class ConvergenceError(Exception):
    """Exception class for convergence error on job"""
    def __init__(self, message="Convergence checks from csv have failed, job not converging and will be deleted"):
        self.message = message
        super().__init__(self.message)

#################################################################


class HPCScheduling:

    ### Init function
     
    def __init__(self) -> None:
        pass

    ### assigning input parametric values as attributes of the SimScheduling class and submitting jobs

    def run(self,pset_dict):
        ###Path and running attributes
        self.pset_dict = pset_dict
        self.run_path = pset_dict['run_path']
        self.base_path = pset_dict['base_path']
        self.convert_path = pset_dict['convert_path']
        self.case_type = pset_dict['case']
        self.run_ID = pset_dict['run_ID']
        self.local_path = pset_dict['local_path']
        self.save_path = pset_dict['save_path']

        if self.case_type == 'geom':

            ### Geometry features
            self.bar_width = pset_dict['bar_width']
            self.bar_thickness = pset_dict['bar_thickness']
            self.bar_angle = pset_dict['bar_angle']
            self.pipe_radius = pset_dict['pipe_radius']
            self.max_diameter = pset_dict['max_diameter']
            self.n_bars = pset_dict['n_bars']
            self.flowrate = pset_dict['flowrate']
            self.d_per_level = pset_dict['d_per_level']
            self.n_levels = pset_dict['n_levels']
            self.d_radius = pset_dict['d_radius']
            self.smx_pos = pset_dict['smx_pos']

        else:

            ### Surfactant features
            self.diff1 = pset_dict['D_d']
            self.diff2 = format(float(pset_dict['D_b']),'.10f')
            self.ka = format(float(pset_dict['ka']),'.10f')
            self.kd = format(float(pset_dict['kd']),'.10f')
            self.ginf = format(float(pset_dict['ginf']),'.10f')
            self.gini = format(float(pset_dict['gini']),'.10f')
            self.diffs = format(float(pset_dict['D_s']),'.10f')
            self.beta = format(float(pset_dict['beta']),'.10f')

        self.run_name = "run_"+str(self.run_ID)
        self.path = os.path.join(self.run_path, self.run_name)
        self.base_case_dir = os.path.join(self.base_path, self.case_type)
        self.mainpath = os.path.join(self.run_path,'..')

        ### Creating f90
        print('-' * 100)
        print('F90 CREATION')
        print('-' * 100)

        self.makef90()

        ### Creating job.sh
        print('-' * 100)
        print('JOB.SH CREATION')
        print('-' * 100)

        try:
            self.setjobsh()
        except ValueError as e:
            print(f'Case ID {self.run_ID} failed due to: {e}')
            print("====EXCEPTION====")
            print("ValueError")
            raise ValueError (f'Exited HPC with error {e}')

        ### Submitting job.sh
        print('-' * 100)
        print('JOB SUBMISSION')
        print('-' * 100)

        ### wait time to submit jobs, avoiding them to go all at once
        #init_wait_time = np.random.RandomState().randint(60,180)
        #sleep(init_wait_time)

        job_IDS = self.submit_job(self.path,self.run_name)

        print('-' * 100)
        print(f'Job {self.run_ID} submitted succesfully with ID {job_IDS}')

        #sleep(120)

        ### Check job status and assign waiting time accordingly
        try:
            t_jobwait, status, update_jobID = self.job_wait(job_IDS)
            print("====JOB_IDS====")
            print(update_jobID)
            print("====JOB_STATUS====")
            print(status)
            print("====WAIT_TIME====")
            print(t_jobwait)

        except JobStatError:
            print(f'Job {self.run_ID} failed on initial submission')
            print("====EXCEPTION====")
            print("JobStatError")
        except ValueError:
            print("====EXCEPTION====")
            print("ValueError")

    ### checking jobstate and sleeping until completion or restart commands

    def monitor(self,mdict):
        ### Read dictionary with job_ID to monitor
        self.mdict = mdict
        self.jobID = mdict['jobID']
        self.run_ID = mdict['run_ID']
        self.run_path = mdict['run_path']
        self.check = mdict['check']


        self.run_name = "run_"+str(self.run_ID)
        self.path = os.path.join(self.run_path, self.run_name)

        ### Call job waiting method and extract corresponding outputs
        try:
            t_jobwait, status, newjobid = self.job_wait(
                int(self.jobID))
            print("====JOB_IDS====")
            print(newjobid)
            print("====JOB_STATUS====")
            print(status)
            print("====WAIT_TIME====")
            print(t_jobwait)

            ### If job running, start convergence checks
            if status == 'R' and self.check:
                chk_status = self.check_convergence()

                ### Job likely to diverge, kill the job and raise the exception
                if chk_status == 'D':
                    print('-' * 100)
                    print("====EXCEPTION====")
                    print("ConvergenceError")
                    print('-' * 100)
                    print(f'Job from run {self.run_ID} is failing to converge')
                    print(f'Killing Job ID {self.jobID} from run {self.run_ID}')
                    print('-' * 100)
                    Popen(['qdel', f"{self.jobID}"])

                ### Convergence checks not needed at early stage in the run
                elif chk_status == 'NR':
                    print('-' * 100)
                    print('Convergence check starting condition not met, trying again later...')
                    print('-' * 100)
                ### Csv does not exist, convergence checks skipped
                elif chk_status == 'FNF':
                    print('-' * 100)
                    print('Warning: CSV file not found, cannot execute convergence checks, moving on...')
                    print('-' * 100)

                ### Job running and complying with all set checks
                else:
                    print('-' * 100)
                    print(f'All convergence checks for job {self.run_ID} have passed successfully')
                    print('-' * 100)

        except JobStatError:
            print("====EXCEPTION====")
            print("JobStatError")
        except ValueError:
            print("====EXCEPTION====")
            print("ValueError")
           
    ### creating f90 instance and executable

    def makef90(self):

        ## Create run_ID directory
        os.mkdir(self.path)

        ## Copy base files and rename to current run accordingly
        os.system(f'cp -r {self.base_case_dir}/* {self.path}')
        os.system(f'mv {self.path}/base_SMX.f90 {self.path}/{self.run_name}_SMX.f90')
        print('-' * 100)
        print(f'Run directory {self.path} created and base files copied')

        if self.case_type == 'geom':

            ## Assign values to placeholders
            os.system(f'sed -i \"s/\'pipe_radius\'/{self.pipe_radius}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'smx_pos\'/{self.smx_pos}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'bar_width\'/{self.bar_width}/g\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'bar_thickness\'/{self.bar_thickness}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'bar_angle\'/{self.bar_angle}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'n_bars\'/{self.n_bars}/\" {self.path}/{self.run_name}_SMX.f90')


            os.system(f'sed -i \"s/\'d_per_level\'/{self.d_per_level}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'n_levels\'/{self.n_levels}/\" {self.path}/{self.run_name}_SMX.f90')
            os.system(f'sed -i \"s/\'d_radius\'/{self.d_radius}/\" {self.path}/{self.run_name}_SMX.f90')


            os.system(f'sed -i \"s/\'flowrate\'/{self.flowrate}/\" {self.path}/{self.run_name}_SMX.f90')
            print('-' * 100)
            print(f'Placeholders for geometry specs in {self.run_name}_SMX.f90 modified correctly')
        
        #modify the Makefile

        os.system(f'sed -i s/file/{self.run_name}_SMX/g {self.path}/Makefile')

        #compile the f90 into an executable

        os.chdir(self.path)
        subprocess.run('make',shell=True, capture_output=True, text=True, check=True)
        print('-' * 100)
        print('Makefile created succesfully')
        os.system(f'mv {self.run_name}_SMX.x {self.run_name}.x')
        subprocess.run('make cleanall',shell=True, capture_output=True, text=True, check=True)
        os.chdir('..')

    ### modifying .sh instance accordingly

    def setjobsh(self):
        
        ## rename job with current run
        os.system(f'mv {self.path}/job_base.sh {self.path}/job_{self.run_name}.sh')

        ## Assign values to placeholders
        os.system(f'sed -i \"s/RUN_NAME/{self.run_name}/g\" {self.path}/job_{self.run_name}.sh')

        ### If geometry variations are studied, construct domain and mesh specifications in job.sh accordingly
        if self.case_type == 'geom':

            radius = float(self.pipe_radius)
            max_diameter = float(self.max_diameter)
            d_pipe = 2*radius
            min_res = 18000

            ### Resolution and domain size condition
            if min_res*(2*self.max_diameter)/128 > 16:
                raise ValueError("Max p_diameter doesn't comply with min. res.")

            ## x-subdomain is 2 times the pipe's diameter
            box_2 = math.ceil(4*radius*1000)/1000
            box_4 = math.ceil(2*radius*1000)/1000
            box_6 = math.ceil(2*radius*1000)/1000

            os.system(f'sed -i \"s/\'box2\'/{box_2}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'box4\'/{box_4}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'box6\'/{box_6}/\" {self.path}/job_{self.run_name}.sh')
        
            ## first cut for 64 cells per subd considering max x-subd as 10. ELSE added to consider 128 cells for x-subd and decrease ncpus.
            first_d_cut = (64*10/(2*min_res))/max_diameter
            
            ## Below second cut taking 6 for all subdomains and 128 cells for x-subd.
            second_d_cut = ((6*64)/min_res)/max_diameter 

            ## Above second cut, all subdomains must have 128 cells and set with multiple nodes.

            if d_pipe < first_d_cut*max_diameter:
                cpus = min_res*(2*d_pipe)/64
                if cpus <= 6:
                    xsub = math.ceil(cpus / 2) * 2
                    ysub = zsub = int(xsub/2)
                    mem = 128 
                    cell1 = cell2 = cell3 = 64
                    ncpus = int(xsub*ysub*zsub)
                    n_nodes = 1
                ### GENERAL QUEUE OPTION
                
                # elif cpus < 8:
                #     xsub = math.ceil(cpus / 2) * 2
                #     ysub = zsub = int(xsub/2)
                #     mem = 124 
                #     cell1 = cell2 = cell3 = 64
                #     ncpus = int(xsub*ysub*zsub/4)
                #     n_nodes = 4   
                
                else:
                    xsub = ysub = zsub = math.ceil(min_res*(2*d_pipe)/128)
                    mem = 256
                    ncpus = int(xsub*ysub*zsub)
                    n_nodes=1
                    cell1= 128
                    cell2 = cell3 = 64            
            elif d_pipe > second_d_cut*max_diameter:
                cpus = min_res*(2*d_pipe)/128
                if cpus <= 10:
                    xsub = math.ceil(cpus / 2) * 2
                    ysub = zsub = int(xsub/2)
                    mem = 512
                    cell1 = cell2 = cell3 = 128
                    ncpus = int(xsub*ysub*zsub)
                    n_nodes = 1
                elif cpus >10 and cpus <= 12:
                    xsub = 12
                    ysub = zsub = int(xsub/2)
                    cell1 = cell2 = cell3 = 128
                    n_nodes = 4
                    ncpus = int(xsub*ysub*zsub/n_nodes)
                    mem = 100
                elif cpus >12 and cpus <= 14:
                    xsub = 14
                    ysub = zsub = int(xsub/2)
                    cell1 = cell2 = cell3 = 128
                    n_nodes = 7
                    ncpus = int(xsub*ysub*zsub/n_nodes)
                    mem = 100
                elif cpus > 14 and cpus <=16:
                    xsub = 16
                    ysub = zsub = int(xsub/2)
                    cell1 = cell2 = cell3 = 128
                    n_nodes = 8
                    ncpus = int(xsub*ysub*zsub/n_nodes)
                    mem = 256

            else:
                xsub = ysub = zsub = 6
                mem = 256
                ncpus = int(xsub*ysub*zsub)
                n_nodes=1
                cell1= 128
                cell2 = cell3 = 64

            ### Replacing placeholders in job.sh file after resolution calculations
            os.system(f'sed -i \"s/\'x_subd\'/{xsub}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'y_subd\'/{ysub}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'z_subd\'/{zsub}/\" {self.path}/job_{self.run_name}.sh')

            os.system(f'sed -i \"s/\'n_cpus\'/{ncpus}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'n_nodes\'/{n_nodes}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'mem\'/{mem}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'cell1\'/{cell1}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'cell2\'/{cell2}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'cell3\'/{cell3}/\" {self.path}/job_{self.run_name}.sh')

            print('-' * 100)
            print(f'Placeholders replaced succesfully in job.sh for run:{self.run_ID}')

        elif self.case_type == 'surf':

            ### Replacing placeholders for surfactant parametric study with fixed geometry
            os.system(f'sed -i \"s/\'diff1\'/{self.diff1}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'diff2\'/{self.diff2}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'ka\'/{self.ka}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'kd\'/{self.kd}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'ginf\'/{self.ginf}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'gini\'/{self.gini}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'diffs\'/{self.diffs}/\" {self.path}/job_{self.run_name}.sh')
            os.system(f'sed -i \"s/\'beta\'/{self.beta}/\" {self.path}/job_{self.run_name}.sh')

            print('-' * 100)
            print(f'Placeholders replaced succesfully in job.sh for run:{self.run_ID}')

    ### checking job status and sending exceptions as fitting

    def job_wait(self,job_id):
        try:
            p = Popen(['qstat', '-a',f"{job_id}"],stdout=PIPE, stderr=PIPE)
            output = p.communicate()[0]
        
            if p.returncode != 0:
                raise subprocess.CalledProcessError(p.returncode, p.args)
            
            ## formatted to Imperial HPC, extracting job status and performing actions accordingly 
            jobstatus = str(output,'utf-8').split()[-3:]
            status = jobstatus[1]

            if not jobstatus:
                raise ValueError('Job exists but belongs to another account')
    
            if status == 'Q':
                t_wait = 3600
                newjobid = job_id
            elif status == 'H':
                print(f'Deleting HELD job with old id: {job_id}')
                print('-' * 100)
                Popen(['qdel', f"{job_id}"])
                sleep(60)
                newjobid = self.submit_job(self.path,self.run_name)
                t_wait = 1800
                print(f'Submitted new job with id: {newjobid}')
            elif status == 'R':
                time_format = '%H:%M'
                wall_time = datetime.datetime.strptime(jobstatus[0], time_format).time()
                elap_time = datetime.datetime.strptime(jobstatus[2], time_format).time()
                delta = datetime.datetime.combine(datetime.date.min, wall_time)-datetime.datetime.combine(datetime.date.min, elap_time)
                remaining = delta.total_seconds()+60
                t_wait = remaining
                newjobid = job_id
            else:
                t_wait = 0
                
        except subprocess.CalledProcessError:
            raise JobStatError("qstat output empty, job finished or deleted from HPC run queue")
        
        except ValueError as e:
            print(f"Error: {e}")
            raise ValueError('Existing job but doesnt belong to this account')
            
        return t_wait, status, newjobid

    ### checking if the running job is diverging or not

    def check_convergence(self):

        ### Jumping to ephemeral to read csv and begin checks
        ephemeral_path = os.path.join(os.environ['EPHEMERAL'],self.run_name)
        os.chdir(ephemeral_path)
        chk_status = None

        ### Checking if the csv exists
        if not os.path.exists(f'{self.run_name}.csv'):
            chk_status = 'FNF'
            return chk_status
       
        csv_to_check = pd.read_csv(f'{self.run_name}.csv')

        # verify whether convergence checks can start
        len_to_check = 2000
        if len(csv_to_check) < len_to_check:
            # let the job run for longer, return NotReady NR status
            chk_status = 'NR'
            return chk_status

        else:
            # check the CFL and time step: CFL < dt or CFL drops below a lower bound
            lower_limit = csv_to_check['dt CFL'][5] * 1e-3
            CFL_check = np.any(csv_to_check['dt CFL'] < lower_limit)

            dt_CFL, dt = csv_to_check['dt CFL'].values, csv_to_check['dt'].values
            dt_arr = dt_CFL - dt
            dt_check = np.any(dt_arr < 0)

            ts_check = CFL_check or dt_check
                            
            # check the Max(div): If Max div fluctuates outside a stability threshold
            window_size = 50
            recent = int(len_to_check * 0.5)
            recent_data = csv_to_check.iloc[-recent:]
            stable_threshold = 0.1
            
            moving_avg_div = recent_data['Max(div(V))'].rolling(window=window_size).mean()[::window_size].dropna().values
            relchg_div = np.diff(moving_avg_div) / moving_avg_div[:-1]

            stable_period = int(len(relchg_div) * 0.9)
            stable_count_div = 0

            for rate in relchg_div:
                if abs(rate) < stable_threshold:
                       stable_count_div += 1
                else: 
                       stable_count_div = 0
            div_check = stable_count_div < stable_period
            
            # check the KE: if there is unstable increase (relative change larger than a threshold)
            moving_avg_ke = recent_data['Kinetic Energy'].rolling(window=window_size).mean()[::window_size].dropna().values
            relchg_ke = np.diff(moving_avg_ke) / moving_avg_ke[:-1]

            stable_period = int(len(relchg_ke) * 0.9)
            stable_count_ke = 0

            for rate in relchg_ke:
                if abs(rate) < stable_threshold:
                       stable_count_ke += 1
                else: 
                       stable_count_ke = 0
            ke_check = stable_count_ke < stable_period
            
            ### If all checks fail, raise a diverging D status
            if ts_check and div_check and ke_check:
                chk_status = 'D'
            ### Else keep monitoring with converging status C
            else:
                chk_status = 'C'

            return chk_status

    ### checking termination condition (PtxEast position or real time) 

    def stop_crit(self):
        ephemeral_path = os.path.join(os.environ['EPHEMERAL'],self.run_name)
        os.chdir(ephemeral_path)
        radius = float(self.pipe_radius)

        if self.case_type == 'geom':

            ### Checking if there is a csv file: if not, run cannot be restart in geom case
            if os.path.exists(f'{self.run_name}.csv'):
                ## Checking location of the interface in the x direction -- stopping criterion
                ptxEast_f = pd.read_csv(f'{self.run_name}.csv').iloc[:,63].iloc[-1]
                domain_x = math.ceil(4*radius*1000)/1000
                min_lim = 0.90*domain_x
                return ptxEast_f < min_lim

            ### Else returning none to print the exception in case of geom runs
            else:
                return None
        else:

            if os.path.exists(f'{self.run_name}.csv'):
                ## Checking location of the interface in the x direction -- stopping criterion
                ptxEast_f = pd.read_csv(f'{self.run_name}.csv').iloc[:,63].iloc[-1]
                domain_x = math.ceil(4*radius*1000)/1000
                min_lim = 0.90*domain_x

                ### option to consider an additional termination condition in case csv file does not exist or can't be read
                ### Mainly for surf case with known time termination
                VAR_file_list = glob.glob('VAR_*_*.vtk')
                last_vtk = max(int(file.split("_")[-1].split(".")[0]) for file in VAR_file_list)
                t_n = last_vtk*5e-3 # based on the jobsh base file configuration
                t_f = 0.3 # seconds based on high res SMX simulations

                return ptxEast_f < min_lim and t_n<t_f

            ### Else returning none to print the exception in case of geom runs
            else:
                ### option to consider an additional termination condition in case csv file does not exist or can't be read
                ### Mainly for surf case with known time termination
                VAR_file_list = glob.glob('VAR_*_*.vtk')
                last_vtk = max(int(file.split("_")[-1].split(".")[0]) for file in VAR_file_list)
                t_n = last_vtk*5e-3 # based on the jobsh base file configuration
                t_f = 0.3 # seconds based on high res SMX simulations

                return t_n<t_f

    ### Restarting sh based on termination condition eval and last output restart reached

    def job_restart(self,pset_dict):

        self.pset_dict = pset_dict
        self.run_ID = pset_dict['run_ID']
        self.case_type = pset_dict['case']
        self.run_name = "run_"+str(self.run_ID)
        self.run_path = pset_dict['run_path']
        self.path = os.path.join(self.run_path, self.run_name)
        output_file_path = os.path.join(self.path,f'{self.run_name}.out')

        self.pipe_radius = pset_dict['pipe_radius']

        ### Checking if there is an output file: if not, run did not start - complete correctly
        if not os.path.exists(output_file_path):
            print("====EXCEPTION====")
            print("FileNotFoundError")
            print(f'File {self.run_name}.out does not exist')
            return False
        
        ### If it is case geom and there is no csv to check stop, exit with exception and stop run
        if self.case_type == 'geom' and self.stop_crit() is None:
            print("====EXCEPTION====")
            print("FileNotFoundError")
            print(f'File {self.run_name}.csv does not exist')
            return False
    

        if self.stop_crit():
            os.chdir(self.path)
            line_with_pattern = None

            ### Checking last restart file instance in output file
            with open(f"{self.run_name}.out", 'r') as file:
                lines = file.readlines()
                pattern = 'writing restart file'
                for line in reversed(lines):
                    if pattern in line:
                        line_with_pattern = line.strip()
                        break
            ### Extracting restart number from line
            if line_with_pattern is not None:
                ### searching with re a sequence of 1 or more digits '\d+' in between two word boundaries '\b'
                match = re.search(r"\b\d+\b", line_with_pattern)
                if match is not None:
                    restart_num = int(match.group())
                else:
                    print("====EXCEPTION====")
                    print("ValueError")
                    print('No restart number match found')
                    return False
                ### Modifying .sh file accordingly
                with open(f"job_{self.run_name}.sh", 'r+') as file:
                    lines = file.readlines()
                    restart_line = lines[384]
                    modified_restart = re.sub('FALSE', 'TRUE', restart_line)
                    ### modifying the restart number by searching dynamically with f-strings. 
                    modified_restart = re.sub(r'{}=\d+'.format('input_file_index'), 
                                              '{}={}'.format('input_file_index', restart_num), 
                                              modified_restart)
                    lines[384] = modified_restart
                    file.seek(0)
                    file.writelines(lines)
                    file.truncate()

                ### submitting job with restart modification
                job_IDS = self.submit_job(self.path,self.run_name)
                print('-' * 100)
                print(f'Job {self.run_ID} re-submitted correctly with ID: {job_IDS}')
                sleep(120)

                ### check status and waiting time for re-submitted job
                try:
                    t_jobwait, status, new_jobID = self.job_wait(job_IDS)
                    print("====JOB_IDS====")
                    print(new_jobID)
                    print("====JOB_STATUS====")
                    print(status)
                    print("====WAIT_TIME====")
                    print(t_jobwait)
                    print("====RETURN_BOOL====")
                    print("True")
                    return True
                except JobStatError:
                    print(f'Restart job {self.run_ID} failed on initial re-submission')
                    print("====EXCEPTION====")
                    print("JobStatError")
                except ValueError:
                    print("====EXCEPTION====")
                    print("ValueError")

            else:
                print("====EXCEPTION====")
                print("ValueError")
                print("Restart file pattern in .out not found or does not exist")
                return False
            
        else:
            print('-' * 100)
            print("Job reached completion, no restarts required")
            print("====RETURN_BOOL====")
            print("False")
            return False

    ### Converting vtk to vtr

    def vtk_convert(self,pset_dict):

        self.pset_dict = pset_dict
        self.run_path = pset_dict['run_path']
        self.run_ID = pset_dict['run_ID']
        self.run_name = "run_"+str(self.run_ID)
        self.convert_path = pset_dict['convert_path']
        self.path = os.path.join(self.run_path, self.run_name)

        ### Move to ephemeral and create RESULTS saving folder
        ephemeral_path = os.path.join(os.environ['EPHEMERAL'],self.run_name)

        os.chdir(ephemeral_path)

        try:
            os.mkdir('RESULTS')
            print('-' * 100)
            print(f'RESULTS folder created in {ephemeral_path}')
        except FileExistsError:
            pass

        ### Listing ISO and VAR vtks and pvds
        ISO_file_list = glob.glob('ISO_*.vtk')
        VAR_file_list = glob.glob('VAR_*_*.vtk')
        PVD_file_list = glob.glob('VAR_*_time=*.pvd')
        sorted_PVDs = sorted(PVD_file_list, key = lambda filename: 
                    float(filename.split('=')[-1].split('.pvd')[0]))
        last_vtk = max(int(file.split("_")[-1].split(".")[0]) for file in VAR_file_list)

        ### First and last pvd file for pvpython processing
        pvd_0file = glob.glob(f'VAR_{self.run_name}_time=0.00000E+00.pvd')[0]
        pvd_ffile = sorted_PVDs[-1]
    
        ### Files to be converted, last time step in VAR
        VAR_toconvert_list = glob.glob(f'VAR_*_{last_vtk}.vtk')
        files_to_convert = ISO_file_list + VAR_toconvert_list
        file_count = len(files_to_convert)

        ### Moving files to RESULTS
        for file in files_to_convert:
            try:
                shutil.move(file,'RESULTS')
            except (FileNotFoundError, shutil.Error) as e:
                print('-' * 100)
                print("====EXCEPTION====")
                print("FileNotFoundError")
                print('-' * 100)
                print(f"Exited with message :{e}, File or directory not found.")
                print('-' * 100)
                return

        print('-' * 100)
        print('Convert files copied to RESULTS')

        ### Moving individual files of interest: pvd, csd
        try:
            shutil.move(f'VAR_{self.run_name}.pvd','RESULTS')
            shutil.move(f'ISO_static_1_{self.run_name}.pvd','RESULTS')
            shutil.move(f'{self.run_name}.csv','RESULTS')
            shutil.move(f'{pvd_0file}', 'RESULTS')
            shutil.move(f'{pvd_ffile}', 'RESULTS')
            print('-' * 100)
            print('VAR, ISO and csv files moved to RESULTS')
        except (FileNotFoundError, shutil.Error) as e:
            print('-' * 100)
            print("====EXCEPTION====")
            print("FileNotFoundError")
            print('-' * 100)
            print(f"Exited with message :{e}, File or directory not found.")
            print('-' * 100)
            return

        ### Cleaning previous restart and vtk from ephemeral
        os.system('rm *vtk')
        os.system('rm *rst')

        os.chdir('RESULTS')

        try:
            os.mkdir('VTK_SAVE')
        except FileExistsError:
            pass

        ### Finding, copying and modifying convert files into RESULTS
        convert_scripts = glob.glob(os.path.join(self.convert_path, '*'))

        for file in convert_scripts:
            try:
                shutil.copy2(file, '.')
            except (FileNotFoundError, PermissionError, OSError):
                print("====EXCEPTION====")
                print("FileNotFoundError")
                print(f"Failed to copy '{file}'.")
                return

        os.system(f'sed -i \"s/\'FILECOUNT\'/{file_count}/\" Multithread_pool.py')

        ### Submitting job convert and extracting job_id, wait time and status
        jobid = self.submit_job(os.path.join(ephemeral_path,'RESULTS'),'convert')

        print('-' * 100)
        print(f'JOB CONVERT from {self.run_name} submitted succesfully with ID {jobid}')
        sleep(120)

        try:
            t_jobwait, status, new_jobID = self.job_wait(jobid)
            print("====JOB_IDS====")
            print(new_jobID)
            print("====JOB_STATUS====")
            print(status)
            if status == 'Q' or status == 'H':
                print("====WAIT_TIME====")
                print(t_jobwait-1800)
            elif status == 'R':
                print("====WAIT_TIME====")
                print(t_jobwait)

        except JobStatError:
            print(f'Convert job {self.run_ID} failed on initial submission')
            print("====EXCEPTION====")
            print("JobStatError")

        except ValueError:
            print("====EXCEPTION====")
            print("ValueError")

    ### submitting the SMX job and recording job_id

    def submit_job(self,path,name):

        proc = []
        os.chdir(f'{path}')
        proc = Popen(['qsub', f"job_{name}.sh"], stdout=PIPE)

        output = proc.communicate()[0].decode('utf-8').split()

        ### Search job id from output after qsub
        jobid = int(re.search(r'\b\d+\b',output[0]).group())

        return jobid
    
def main():
    ### Argument parser to specify function to run
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "function",
        choices=["run","monitor","job_restart","vtk_convert"], 
    )

    ### Input argument for dictionary
    parser.add_argument(
        "--pdict",
        type=json.loads,
    )

    args = parser.parse_args()

    simulator = HPCScheduling()

    if hasattr(simulator, args.function):
        func = getattr(simulator, args.function)
        func(args.pdict)
    else:
        print("Invalid function name")

if __name__ == "__main__":
    main()

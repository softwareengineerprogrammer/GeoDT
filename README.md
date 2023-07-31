# GeoDT

**Developed by Luke P. Frash**

## General:
This Geothermal Design Tool (GeoDT) is a fast multi-well flow and heat transfer model intended to aid high-level decision making 
for enhanced geothermal systems - geothermal energy development. This tool: 
1. generates a 3D geometry that includes wells and fractures
1. assigns dimensionally-scaled properties these wells and fractures
1. creates a mesh of 1D pipes and nodes to represent hydraulic connectivity in the 3D well and fracture network
1. solves this 1D network for fluid flow based on user assigned boundary conditions
1. predicts natural fracture and hydraulic fracture stimulation by fluid injection
1. solves this 1D network for time-dependent heat production
1. estimates transient net electrical power production from the network
1. outputs a csv file that summarizes the input and output parameters
1. outputs vtk files for visualizing the system geometry
1. provides statistical data visualization example scripts and plots

*This code is in active development. We appreciate comments and questions that will help to improve this project.*

![](Intro%20Graphic.png)

## File descriptions:
- `GeoDT.py`: main program to create and analyze fracture-well system geothermal productivity
- `GeoDTviewer.py`: supporting scripts for statistical analysis and plotting of multiple GeoDT runs using the csv file output 
from GeoDT and an input
- `documentation/`: information about the input and output variables and the model's methods
- `examples/`: example scripts that run GeoDT using the input values as specified in the example scripts
- `libs/`: GeoDT subroutines

## Instructions for first run (assumes that you are working from install directory):

### Set up [Virtual Environment](https://virtualenv.pypa.io/en/latest/) (strongly recommended)

```shell
python -m venv ./venv
pip install --upgrade pip
pip install -r requirements.txt
source venv/bin/activate
```

If you do not set up virtualenv, you will need to ensure that the dependencies in `requirements.txt` are installed in global site packages (`pip install -r requirements.txt`)

### Steps
1. Pick an example script from `examples/` and copy it to the main directory
    - `validation_` files generally specify deterministic geometries and boundary conditions
    - `example_` files are generally stochastic multi-run models that focus on EGS design optimization
1. Set your python working directory to a location where you want the output files to be created, i.e. `mkdir -p build && rm build/*`
1. Run the example script i.e. `cd build && python ./example_datathon_2023.py`
1. View the result vtk files using a compatible visualization software (e.g., [ParaView](https://www.paraview.org/))
1. Inspect the example script and edit as needed to customize to your modeling goals


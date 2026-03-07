* PDK include file for IHP SG13G2
* DO NOT EDIT — this file is the PDK interface layer

* Corner model selection (default: typical)
* Override by setting params before .include, or use .lib directly in testbench

.lib cornerMOSlv.lib mos_tt
.lib cornerHBT.lib hbt_typ
.lib cornerRES.lib res_typ
.lib cornerCAP.lib cap_typ

# def tact_gem
## runs tact on gem file
## written by Quinten Vanhellemont, RBINS
## 2021-02-28
## modifications: 2021-02-28 (QV) allow gem to be a dict
##                2022-03-22 (QV) added check whether thermal bands are in input gem
##                2022-07-31 (QV) skip loading of datasets that are not required
##                2022-08-02 (QV) added source keyword
##                2022-08-03 (QV) added external emissivity files

def tact_gem(gem, output_file = True,
             return_data = False,
             target_file = None,
             target_file_append = False,
             #output = None,
             to_celcius = False,
             #emissivity = 'water', # 'unity' / 'water' / 'eminet' / 'user'
             #emissivity_file = None,
             sub = None,
             #output_atmosphere = False,
             #output_intermediate = False,
             copy_datasets = ['lon', 'lat'],
             #source = 'era5',
             settings = {}, verbosity=0):

    import os, datetime, json
    import numpy as np
    import acolite as ac

    ## determine datasets to skip
    if type(gem) is str:
        datasets = ac.shared.nc_datasets(gem)
    else:
        datasets = gem['datasets']

    skip_datasets = []
    for ds in datasets:
        if ds in ['lat', 'lon']: continue
        if ds[0:2] == 'bt': continue
        if ds[0:2] == 'lt': continue
        skip_datasets.append(ds)

    ## read gem file if NetCDF
    if type(gem) is str:
        gemf = '{}'.format(gem)
        gem = ac.gem.read(gem, sub=sub, skip_datasets=skip_datasets)
    gemf = gem['gatts']['gemfile']

    ## settings from settings dict
    setu = ac.acolite.settings.parse(gem['gatts']['sensor'], settings=settings)
    output = setu['output']
    emissivity = setu['tact_emissivity']
    emissivity_file = setu['tact_emissivity_file']
    source = setu['tact_profile_source']
    output_atmosphere = setu['tact_output_atmosphere']
    output_intermediate = setu['tact_output_intermediate']
    reptran = setu['tact_reptran']

    ## detect sensor
    if ('thermal_sensor' not in gem['gatts']) or ('thermal_bands' not in gem['gatts']):
        if verbosity > 0: print('TACT Processing of {} not supported'.format(gem['gatts']['sensor']))
        return()

    ## check if we need to run tact
    run_tact = False
    for b in gem['gatts']['thermal_bands']:
        dsi = 'bt{}'.format(b)
        if dsi in gem['datasets']: run_tact = True
    if not run_tact:
        print('No thermal bands for {} (bands {}) in {}'.format(gem['gatts']['sensor'], ','.join(gem['gatts']['thermal_bands']), gemf))
        return()

    ## check blackfill
    if setu['blackfill_skip']:
        for b in gem['gatts']['thermal_bands']:
            if 'bt{}'.format(b) in gem['data']:
                band_data = 1.0*gem['data']['bt{}'.format(b)]
                break
        npx = band_data.shape[0] * band_data.shape[1]
        #nbf = npx - len(np.where(np.isfinite(band_data))[0])
        nbf = npx - len(np.where(np.isfinite(band_data)*(band_data>0))[0])
        band_data = None
        if (nbf/npx) >= float(setu['blackfill_max']):
            if verbosity>0: print('Skipping scene as crop is {:.0f}% blackfill'.format(100*nbf/npx))
            return()

    if source == 'era5':
        max_date = (datetime.datetime.now() - datetime.timedelta(days=90)).isoformat()
        if gem['gatts']['isodate'] > max_date:
            print('File too recent for TACT with {} profiles: after {}'.format(source, max_date))
            print('Run with tact_profile_source=gdas1 or tact_profile_source=ncep.reanalysis2 for NRT processing')
            return()

    ## load emissivity data
    if emissivity_file is not None:
        if not os.path.exists(emissivity_file):
            print('Could not file {}'.format(emissivity_file))
            emissivity_file = None
    if (emissivity_file is None) & (emissivity not in ['ged', 'eminet', 'ndvi']):
        emissivity_file = '{}/{}/emissivity_{}.json'.format(ac.config['data_dir'], 'TACT', emissivity)
        if not os.path.exists(emissivity_file):
            print('Could not file {}'.format(emissivity_file))
            emissivity_file = None
    if emissivity_file is not None:
        em = json.load(open(emissivity_file, 'r'))
        print('Loaded emissivity file {}'.format(emissivity_file))
        print(em)
    else:
        em = None

    if 'nc_projection' in gem:
        nc_projection = gem['nc_projection']
    else:
        nc_projection = None

    if verbosity > 0: print('Running tact for {}'.format(gemf))

    if target_file is None:
        #if 'output_name' in gem['gatts']:
        #    output_name = gem['gatts']['output_name']
        #elif 'oname' in gem['gatts']:
        #    output_name = gem['gatts']['oname']
        #else:
        #    output_name = os.path.basename(gemf).replace('.nc', '')
        output_name = os.path.basename(gemf).replace('.nc', '')
        output_name = output_name.replace('_L1R', '')
        output_name = output_name.replace(gem['gatts']['sensor'], gem['gatts']['thermal_sensor'])
        odir = output if output is not None else os.path.dirname(gemf)
        ofile = '{}/{}_ST.nc'.format(odir, output_name)
    else:
        ofile = '{}'.format(target_file)

    print('Running ACOLITE/TACT for {}'.format(gemf))

    ## datasets to write
    output_datasets = []
    for ds in copy_datasets: output_datasets.append(ds)

    ## radiative transfer
    thd, simst, lonc, latc = ac.tact.tact_limit(gem['gatts']['isodate'],
                                                lon=gem['data']['lon'],
                                                lat=gem['data']['lat'],
                                                satsen=gem['gatts']['thermal_sensor'],
                                                reptran = reptran, source = source)
    for ds in thd:
        gem['data'][ds] = thd[ds]
        ## output atmosphere parameters
        if output_atmosphere: output_datasets += [ds]
    thd = None


    ## read bands and do thermal a/c
    em_ged, em_eminet, em_ndvi = None, None, None
    for b in gem['gatts']['thermal_bands']:
        dsi = 'bt{}'.format(b)

        if dsi in gem['datasets']:
            btk = 'bt{}'.format(b)
            ltk = 'lt{}'.format(b)
            lsk = 'ls{}'.format(b)
            emk = 'em{}'.format(b)
            dso = 'st{}'.format(b)

            if output_intermediate: output_datasets += [btk, ltk, lsk, emk]
            output_datasets += [dso]

            #gd['data'][btk] = ac.shared.nc_data(ncf, dsi, sub=sub)
            #mask = gem['data'][btk].mask
            #gem['data'][btk] = gem['data'][btk].data
            #gem['data'][btk][mask] = np.nan

            bk = b.split('_')[0]
            e = None
            if emissivity == 'ged':
                if em_ged is None:
                    ## determine bands
                    if gem['gatts']['thermal_sensor'] in ['L8_TIRS', 'L9_TIRS']:
                        bands = [13, 14]
                        bkeys = {'10':0, '11':1}
                    elif gem['gatts']['thermal_sensor'] in ['L5_TM', 'L7_ETM']:
                        bands = [13]
                        bkeys = {'6':0}
                    elif gem['gatts']['thermal_sensor'] in ['ISS_ECOSTRESS']:
                        bands = [10, 11, 12, 13, 14]
                        bkeys = {'1':0, '2':1, '3':2, '4':3, '5':4}
                    ## load GED emissivity
                    em_ged = ac.ged.ged_lonlat(gem['data']['lon'], gem['data']['lat'], bands=bands, fill = setu['ged_fill'])
                if em_ged is None:
                    print('Could not extract GED emissivity.')
                else:
                    if len(em_ged.shape) == 3:
                        e = em_ged[:,:,bkeys[b]]
                    else:
                        e = em_ged * 1.0
            if emissivity == 'eminet':
                if em_eminet is None:
                    em_eminet = ac.tact.tact_eminet(gemf, water_fill = setu['eminet_water_fill'],
                                                       water_threshold = setu['eminet_water_threshold'],
                                                       model_version = setu['eminet_model_version'],
                                                       netname = setu['eminet_netname'],
                                                       fill = setu['eminet_fill'],
                                                       fill_dilate = setu['eminet_fill_dilate'])
                if em_eminet is None:
                    print('Could not get EMINET emissivity.')
                else:
                    e = em_eminet[bk]

            if emissivity == 'ndvi':
                if em_ndvi is None:
                    em_ndvi = ac.tact.ndvi_emissivity(gemf, ndvi_toa=True)
                if em_ndvi is None:
                    print('Could not get NDVI derived emissivity.')
                else:
                    e = em_ndvi[bk]

            if (e is None) & (em is not None):
                e = em[gem['gatts']['thermal_sensor']][bk]
                #print(e, gem['gatts']['thermal_sensor'], bk)

            if e is None:
                print('Emissivity for {} {} not configured.'.format(gem['gatts']['thermal_sensor'], bk))
                print('Ls and ST will not be computed for {} {}.'.format(gem['gatts']['thermal_sensor'], bk))
                continue

            ## shape emissivity to tile dimensions
            gem['data'][emk] = np.atleast_2d(e)
            if gem['data'][emk].shape == (1,1):
                gem['data'][emk] = np.tile(gem['data'][emk], gem['data']['lat'].shape)

            ## K constants
            k1 = float(gem['gatts']['K1_CONSTANT_BAND_{}'.format(b.upper())])
            k2 = float(gem['gatts']['K2_CONSTANT_BAND_{}'.format(b.upper())])

            if ltk not in gem['data']:
                ## compute lt from bt
                #bt = k2/(np.log(k1/lt)+1)
                #lt = k1/(np.exp(k2/bt)-1)
                gem['data'][ltk] = k1/(np.exp(k2/gem['data'][btk])-1)

            ## get surface radiance
            #ls = (((lt-thd['Lu{}'.format(bk)])/thd['tau{}'.format(bk)])-((1-e)*thd['Ld{}'.format(bk)]))/e
            gem['data'][lsk] = (((gem['data'][ltk]-gem['data']['Lu{}'.format(bk)])/gem['data']['tau{}'.format(bk)])-((1-gem['data'][emk])*gem['data']['Ld{}'.format(bk)]))/gem['data'][emk]

            ## convert to surface temperature
            #st = (k2/np.log((k1/ls)+1))
            gem['data'][dso] = (k2/np.log((k1/gem['data'][lsk])+1))
            if to_celcius: gem['data'][dso] += -273.15


    ## write output NetCDF
    if output_file:
        gem['gatts']['acolite_file_type'] = 'L2T'
        gem['gatts']['ofile'] = ofile
        gem['gatts']['sensor'] = gem['gatts']['thermal_sensor']

        new = True
        datasets_ofile = []
        if os.path.exists(ofile) & target_file_append:
            datasets_ofile = ac.shared.nc_datasets(ofile)
            new = False
        for ds in output_datasets:
            if ds in datasets_ofile: continue
            if ds not in gem['data']: continue
            ds_att = None
            if ds in gem['atts']: ds_att = gem['atts'][ds]
            ac.output.nc_write(ofile, ds, gem['data'][ds], new=new, nc_projection=nc_projection,
                               attributes=gem['gatts'], dataset_attributes=ds_att)
            if verbosity > 1: print('Wrote {} to {}'.format(ds, ofile))
            new=False
        if verbosity > 0: print('Wrote {}'.format(ofile))

    if return_data: return(gem)
    return(ofile)

Attributes {
    forecast_reference_time {
        String units "seconds since 1970-01-01 00:00:00 +00:00";
        String standard_name "forecast_reference_time";
    }
    mean_sea_level {
        String long_name "mean_sea_level";
        String description "mean sea level";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    surface {
        String long_name "surface";
        String description "ground or water surface";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    pressure {
        String long_name "pressure";
        String description "pressure";
        String standard_name "air_pressure";
        String positive "down";
        String units "hPa";
        UInt32 _ChunkSizes 13;
    }
    height_above_msl {
        String long_name "height";
        String description "height above MSL";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height0 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height1 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height2 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 2;
    }
    height3 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height4 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height5 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 10;
    }
    height6 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    height7 {
        String long_name "height";
        String description "height above ground";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    hybrid {
        String long_name "atmosphere_hybrid_sigma_pressure_coordinate";
        String standard_name "atmosphere_hybrid_sigma_pressure_coordinate";
        String formula "p(n,k,j,i) = ap(k) + b(k)*ps(n,j,i)";
        String formula_terms "ap: ap b: b ps: surface_air_pressure p0: p0";
        String positive "down";
        UInt32 _ChunkSizes 65;
    }
    p0 {
        String units "Pa";
    }
    ap {
        String units "Pa";
        UInt32 _ChunkSizes 65;
    }
    b {
        String units "1";
        UInt32 _ChunkSizes 65;
    }
    grib2_vLevel14 {
        String long_name "grib2-level 14";
        String units "1";
        UInt32 _ChunkSizes 1;
    }
    grib2_vLevel16 {
        String long_name "grib2-level 16";
        String units "1";
        UInt32 _ChunkSizes 1;
    }
    local_vertical_level_192 {
        String long_name "isotherm zero wet bulb";
        String description "level of isotherm zero wet bulb";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    isotherm_0C_level {
        String long_name "isotherm 0C";
        String description "level of 0degreeC isotherm";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    isotherm_0C_level_from_above {
        String long_name "isotherm 0C from above";
        String description "level of 0degreeC isotherm from above";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    adiabatic_condensation_level {
        String long_name "Adiabatic condensation level";
        String positive "up";
        String units "m";
        UInt32 _ChunkSizes 1;
    }
    maximum_wind_level {
        String long_name "max wind level";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    tropopause {
        String long_name "Tropopause";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    top_of_atmosphere {
        String long_name "nominal top of atmosphere";
        String positive "up";
        UInt32 _ChunkSizes 1;
    }
    projection_lambert {
        String grid_mapping_name "lambert_conformal_conic";
        Float64 standard_parallel 63.3, 63.3;
        Float64 longitude_of_central_meridian 15.0;
        Float64 latitude_of_projection_origin 63.3;
        Float64 earth_radius 6371000.0;
    }
    x {
        String long_name "x-coordinate in Cartesian system";
        String standard_name "projection_x_coordinate";
        String units "m";
        UInt32 _ChunkSizes 949;
    }
    y {
        String long_name "y-coordinate in Cartesian system";
        String standard_name "projection_y_coordinate";
        String units "m";
        UInt32 _ChunkSizes 1069;
    }
    longitude {
        String long_name "longitude";
        String units "degree_east";
        String standard_name "longitude";
        UInt32 _ChunkSizes 1069, 949;
    }
    latitude {
        String long_name "latitude";
        String units "degree_north";
        String standard_name "latitude";
        UInt32 _ChunkSizes 1069, 949;
    }
    time {
        String long_name "time";
        String standard_name "time";
        String units "seconds since 1970-01-01 00:00:00 +00:00";
        UInt32 _ChunkSizes 1;
    }
    integral_of_toa_net_downward_shortwave_flux_wrt_time_assuming_clear_sky {
        Float32 _FillValue 9.96921E36;
        String long_name "TOA SW net clear sky rad";
        String metno_name "integral_of_toa_net_downward_shortwave_flux_assuming_clear_sky_wrt_time";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_net_downward_shortwave_flux_wrt_time_assuming_clear_sky {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface SW net clear sky rad";
        String metno_name "integral_of_surface_net_downward_shortwave_flux_assuming_clear_sky_wrt_time";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_toa_net_downward_longwave_flux_wrt_time_assuming_clear_sky {
        Float32 _FillValue 9.96921E36;
        String long_name "TOA LW net clear sky rad";
        String metno_name "integral_of_toa_net_downward_longwave_flux_wrt_time_assuming_clear_sky";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_net_downward_longwave_flux_wrt_time_assuming_clear_sky {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface LW net clear sky rad";
        String metno_name "integral_of_surface_net_downward_longwave_flux_wrt_time_assuming_clear_sky";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_parallel_solar_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated surface SW downwelling radiation";
        String metno_name "integral_of_surface_parallel_solar_flux_wrt_time";
        String units "J/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_toa_downwelling_shortwave_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "TOA Accumulated SW downwelling radiation";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_direct_normal_irradiance_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface direct normal irradiance accumulated";
        String units "J m-2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    land_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Land-Sea Mask (LSM)";
        String standard_name "land_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_aerosol_sea {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface aerosol sea (Marine aerosols)";
        String metno_name "surface_aerosol_sea";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_aerosol_land {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface aerosol land (Continental aerosols)";
        String metno_name "surface_aerosol_land";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_aerosol_soot {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface aerosol sea soot";
        String metno_name "surface_aerosol_soot";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_aerosol_desert {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface aerosol sea desert";
        String metno_name "surface_aerosol_desert";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    ozone_profile_a {
        Float32 _FillValue 9.96921E36;
        String long_name "SURFA OZONE. First ozone profile (A)";
        String metno_name "ozone_profile";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    ozone_profile_b {
        Float32 _FillValue 9.96921E36;
        String long_name "SURFB OZONE. Second ozone profile (B)";
        String metno_name "ozone_profile";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    ozone_profile_c {
        Float32 _FillValue 9.96921E36;
        String long_name "SURFC OZONE. Third ozone profile (C)";
        String metno_name "ozone_profile";
        String units "";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    specific_humidity_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Specific humidity model levels";
        String standard_name "specific_humidity";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_cloud_condensed_water_in_air_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Atmospheric cloud condensed water content in model levels";
        String standard_name "mass_fraction_of_cloud_condensed_water_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_cloud_ice_in_air_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Mass fraction of cloud ice in model levels";
        String standard_name "mass_fraction_of_cloud_ice_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_snow_in_air_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous snow in model levels";
        String standard_name "mass_fraction_of_snow_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_rain_in_air_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous rain in model levels";
        String standard_name "mass_fraction_of_rain_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_graupel_in_air_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous graupel in model levels";
        String standard_name "mass_fraction_of_graupel_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    turbulent_kinetic_energy_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Turbulent kinetic energy (TKE)";
        String metno_name "turbulent_kinetic_energy";
        String units "m^2/s^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_area_fraction_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud cover in model levels";
        String standard_name "cloud_area_fraction";
        String units "%";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    graupelfall_amount {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous graupel at surface";
        String standard_name "graupel_fall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    toa_net_downward_shortwave_flux {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous TOA net downward SW radiation";
        String standard_name "toa_net_downward_shortwave_flux";
        String units "W/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_downwelling_shortwave_flux_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous surface SW downwelling radiation";
        String standard_name "surface_downwelling_shortwave_flux_in_air";
        String units "W/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    toa_outgoing_longwave_flux {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous TOA outgoing LW radiation flux";
        String standard_name "toa_outgoing_longwave_flux";
        String units "W/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_downwelling_longwave_flux_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous surface LW downwelling radiation";
        String standard_name "surface_downwelling_longwave_flux_in_air";
        String units "W/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    convective_cloud_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Convective cloud cover";
        String standard_name "convective_cloud_area_fraction";
        String units "%";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    hail_diagnostic {
        Float32 _FillValue 9.96921E36;
        String long_name "Hail diagnostic";
        String metno_name "hail_diagnostic";
        String units "%";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Air temperature model levels";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along x-coordinate on model levels";
        String standard_name "x_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along y-coordinate on model levels";
        String standard_name "y_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    upward_air_velocity_ml {
        Float32 _FillValue 9.96921E36;
        String long_name "Vertical vind model levels";
        String standard_name "upward_air_velocity";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_binary_mask {
        Float32 _FillValue 9.96921E36;
        String long_name "";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_max_icing {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of max icing";
        String metno_name "atmosphere_level_of_max_icing";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_max_icing_growth {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of max icing growth";
        String metno_name "atmosphere_level_of_max_icing_growth";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_icing_bottom {
        Float32 _FillValue 9.96921E36;
        String long_name "Bottom level of icing";
        String metno_name "atmosphere_level_of_icing_bottom";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_icing_top {
        Float32 _FillValue 9.96921E36;
        String long_name "Top level of icing";
        String metno_name "atmosphere_level_of_icing_top";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_max_wind_speed {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of max wind speed";
        String metno_name "atmosphere_level_of_max_wind_speed";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_at_maximum_wind_speed_level {
        Float32 _FillValue 9.96921E36;
        String long_name "Max U-component in column";
        String metno_name "x_wind_at_maximum_wind_speed_level";
        String units "m s-1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_at_maximum_wind_speed_level {
        Float32 _FillValue 9.96921E36;
        String long_name "Max V-component in column";
        String metno_name "y_wind_at_maximum_wind_speed_level";
        String units "m s-1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_base_altitude {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud base altitude";
        String standard_name "cloud_base_altitude";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_top_altitude {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud top altitude";
        String standard_name "cloud_top_altitude";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_base_altitude_z {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud top altitude";
        String standard_name "cloud_base_altitude";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    lightning_index {
        Float32 _FillValue 9.96921E36;
        String long_name "Lightning index";
        String metno_name "lightning_index";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    level_of_max_CAT_index {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of max CAT index";
        String metno_name "level_of_max_CAT_index";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    max_cat_index {
        Float32 _FillValue 9.96921E36;
        String long_name "MAX CAT index";
        String metno_name "max_cat_index";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    bottom_level_of_CAT {
        Float32 _FillValue 9.96921E36;
        String long_name "Bottom level of CAT";
        String metno_name "bottom_level_of_CAT";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    top_level_of_CAT {
        Float32 _FillValue 9.96921E36;
        String long_name "Top level of CAT";
        String metno_name "top_level_of_CAT";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    visibility_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Visibility in air";
        String standard_name "visibility_in_air";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    precipitation_type {
        Float32 _FillValue 9.96921E36;
        String long_name "Precipitation type";
        String metno_name "precipitation_type";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    brunt_vaisala_frequency_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Brunt Vaisala frequency";
        String standard_name "brunt_vaisala_frequency_in_air";
        String units "s-1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_downward_latent_heat_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated surface latent heat flux";
        String standard_name "integral_of_surface_downward_latent_heat_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    icing_index {
        Float32 _FillValue 9.96921E36;
        String long_name "Icing index";
        String metno_name "icing_index";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_0m {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface temperature (T0M)";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_geopotential {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface geopotential (fis)";
        String standard_name "surface_geopotential";
        String units "m^2/s^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along x-coordinate on pressure levels";
        String standard_name "x_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_z {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along x-coordinate on height levels";
        String standard_name "x_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 2, 1069, 949;
    }
    liquid_water_content_of_surface_snow {
        Float32 _FillValue 9.96921E36;
        String long_name "Snow Water Equivivalent (SWE)";
        String standard_name "liquid_water_content_of_surface_snow";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_net_downward_shortwave_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated net downward surface SW radiation";
        String standard_name "integral_of_surface_net_downward_shortwave_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along y-coordinate on pressure levels";
        String standard_name "y_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_net_downward_longwave_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated net downward surface LW radiation";
        String standard_name "integral_of_surface_net_downward_longwave_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_downward_latent_heat_evaporation_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated latent heat evaporation flux";
        String metno_name "integral_of_surface_downward_latent_heat_evaporation_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Air temperature pressure levels";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_z {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind along y-coordinate on height levels";
        String standard_name "y_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 2, 1069, 949;
    }
    integral_of_surface_downward_latent_heat_sublimation_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated latent heat sublimation flux at surface";
        String metno_name "integral_of_surface_downward_latent_heat_sublimation_flux_wrt_time";
        String units "J/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_downward_sensible_heat_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated downwelling surface sensible heat flux";
        String standard_name "integral_of_surface_downward_sensible_heat_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    specific_humidity_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Specific humidity pressure levels";
        String standard_name "specific_humidity";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    downward_eastward_momentum_flux_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Momentum flux x-direction";
        String standard_name "downward_eastward_momentum_flux_in_air";
        String units "N/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    downward_northward_momentum_flux_in_air {
        Float32 _FillValue 9.96921E36;
        String long_name "Momentum flux y-direction";
        String standard_name "downward_northward_momentum_flux_in_air";
        String units "N/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_cloud_condensed_water_in_air_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Atmospheric cloud condensed water content in pressure levels";
        String standard_name "mass_fraction_of_cloud_condensed_water_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_z {
        Float32 _FillValue 9.96921E36;
        String long_name "Air temperature height levels";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 2, 1069, 949;
    }
    integral_of_toa_net_downward_shortwave_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated TOA net downward SW radiation";
        String standard_name "integral_of_toa_net_downward_shortwave_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_toa_outgoing_longwave_flux_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated TOA outgoing LW radiation flux";
        String standard_name "integral_of_toa_outgoing_longwave_flux_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_cloud_ice_in_air_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Mass fraction of cloud ice in pressure levels";
        String standard_name "mass_fraction_of_cloud_ice_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    water_evaporation_amount {
        Float32 _FillValue 9.96921E36;
        String long_name "Water evaporation amount";
        String standard_name "water_evaporation_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_snow_sublimation_amount_acc {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated Snow Sublimation";
        String standard_name "surface_snow_sublimation_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    relative_humidity_z {
        Float32 _FillValue 9.96921E36;
        String long_name "Relative humidity height levels";
        String standard_name "relative_humidity";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 2, 1069, 949;
    }
    integral_of_surface_downwelling_shortwave_flux_in_air_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated surface SW downwelling radiation";
        String standard_name "integral_of_surface_downwelling_shortwave_flux_in_air_wrt_time";
        String units "W s/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_surface_downwelling_longwave_flux_in_air_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated surface LW downwelling radiation";
        String standard_name "integral_of_surface_downwelling_longwave_flux_in_air_wrt_time";
        String units "J/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_area_fraction_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Total cloud cover (TCC) in pressure levels";
        String standard_name "cloud_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_rainfall_amount_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated rainfall at surface";
        String standard_name "rainfall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_snowfall_amount_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated snowfall amount at surface";
        String standard_name "snowfall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_snow_in_air_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous snow in pressure levels";
        String standard_name "mass_fraction_of_snow_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    surface_air_pressure {
        Float32 _FillValue 9.96921E36;
        String long_name "Surface air pressure";
        String standard_name "surface_air_pressure";
        String units "Pa";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    integral_of_graupelfall_amount_wrt_time {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated graupel at surface";
        String standard_name "graupel_fall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_2m {
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level temperature (T2M)";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_rain_in_air_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous rain in pressure levels";
        String standard_name "mass_fraction_of_rain_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    tropopause_air_temperature {
        Float32 _FillValue 9.96921E36;
        String long_name "Tropopause air temperature";
        String standard_name "tropopause_air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    relative_humidity_2m {
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity (RH2M)";
        String standard_name "relative_humidity";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    specific_humidity_2m {
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity";
        String standard_name "specific_humidity";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    mass_fraction_of_graupel_in_air_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous graupel in pressure levels";
        String standard_name "mass_fraction_of_graupel_in_air";
        String units "kg/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    tropopause_air_pressure {
        Float32 _FillValue 9.96921E36;
        String long_name "Tropopause air pressure";
        String standard_name "tropopause_air_pressure";
        String units "Pa";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_10m {
        Float32 _FillValue 9.96921E36;
        String long_name "10 metre wind along x-coordinate (U10M)";
        String standard_name "x_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_10m {
        Float32 _FillValue 9.96921E36;
        String long_name "10 metre wind along y-coordinate (V10M)";
        String standard_name "y_wind";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    turbulent_kinetic_energy_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Turbulent kinetic energy (TKE)";
        String metno_name "turbulent_kinetic_energy";
        String units "m^2/s^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    altitude_of_isoTprimW_equal_0 {
        Float32 _FillValue 9.96921E36;
        String long_name "altitude_of_isoTprimW_equal_0";
        String metno_name "altitude_of_isoTprimW";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    cloud_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Total cloud cover (TCC)";
        String standard_name "cloud_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    high_type_cloud_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud cover of high clouds (HCC)";
        String standard_name "high_type_cloud_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    specific_convective_available_potential_energy {
        Float32 _FillValue 9.96921E36;
        String long_name "Convective Available Potential Energy (CAPE)";
        String standard_name "specific_convective_available_potential_energy";
        String units "J/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    medium_type_cloud_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud cover of medium height clouds (MCC)";
        String standard_name "medium_type_cloud_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    low_type_cloud_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Cloud cover of low clouds (LCC)";
        String standard_name "low_type_cloud_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    geopotential_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Geopotential pressure levels";
        String standard_name "geopotential";
        String units "m^2/s^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_convective_inhibition {
        Float32 _FillValue 9.96921E36;
        String long_name "Atmosphere convective inhibition (CIN)";
        String standard_name "atmosphere_convective_inhibition";
        String units "J/kg";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    x_wind_gust_10m {
        Float32 _FillValue 9.96921E36;
        String long_name "U-momentum of gusts in 10m height";
        String metno_name "x_wind_gust";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    y_wind_gust_10m {
        Float32 _FillValue 9.96921E36;
        String long_name "V-momentum of gusts in 10m height";
        String metno_name "y_wind_gust";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    relative_humidity_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Relative humidity pressure levels";
        String standard_name "relative_humidity";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    lifting_condensation_level {
        Float32 _FillValue 9.96921E36;
        String long_name "Atmosphere lifting condensation level wrt surface (LCL)";
        String standard_name "atmosphere_lifting_condensation_level_wrt_surface";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_max {
        Float32 _FillValue 9.96921E36;
        String long_name "Max screen level temperature last hour";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_temperature_min {
        Float32 _FillValue 9.96921E36;
        String long_name "Min screen level temperature last hour";
        String standard_name "air_temperature";
        String units "K";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    upward_air_velocity_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Vertical vind pressure levels";
        String standard_name "upward_air_velocity";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_free_convection {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of free convection wrt surface (LFC)";
        String standard_name "atmosphere_level_of_free_convection_wrt_surface";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_boundary_layer_thickness {
        Float32 _FillValue 9.96921E36;
        String long_name "Height of the PBL";
        String standard_name "atmosphere_boundary_layer_thickness";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    rainfall_amount {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantanous rainfall at surface";
        String standard_name "rainfall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    ertel_potential_vorticity_pl {
        Float32 _FillValue 9.96921E36;
        String long_name "Potential vorticity";
        String standard_name "ertel_potential_vorticity";
        String units "K m2 kg-1 s-1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    atmosphere_level_of_neutral_buoyancy {
        Float32 _FillValue 9.96921E36;
        String long_name "Level of neutral buoyancy (LNB)";
        String metno_name "atmosphere_level_of_neutral_buoyancy_wrt_surface";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    snowfall_amount {
        Float32 _FillValue 9.96921E36;
        String long_name "Instantaneous snowfall amount at surface";
        String standard_name "snowfall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    air_pressure_at_sea_level {
        Float32 _FillValue 9.96921E36;
        String long_name "Mean Sea Level Pressure (MSLP)";
        String standard_name "air_pressure_at_sea_level";
        String units "Pa";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    lwe_thickness_of_atmosphere_mass_content_of_water_vapor {
        Float32 _FillValue 9.96921E36;
        String long_name "Precipitable water";
        String standard_name "lwe_thickness_of_atmosphere_mass_content_of_water_vapor";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    wind_direction {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind direction";
        String standard_name "wind_from_direction";
        String units "degree";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    wind_speed {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind speed";
        String standard_name "wind_speed";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    precipitation_amount_acc {
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated total precipitation";
        String standard_name "precipitation_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    snowfall_amount_acc {
        Float32 _FillValue 9.96921E36;
        String long_name "Total accumulated solid precipitation (snow+graupel+hail)";
        String standard_name "snowfall_amount";
        String units "kg/m^2";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    wind_speed_of_gust {
        Float32 _FillValue 9.96921E36;
        String long_name "Wind gust";
        String standard_name "wind_speed_of_gust";
        String units "m/s";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    altitude_of_0_degree_isotherm {
        Float32 _FillValue 9.96921E36;
        String long_name "Altitude of 0-degree isotherm";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    altitude_of_0_degree_isotherm_from_above {
        Float32 _FillValue 9.96921E36;
        String long_name "Altitude of 0-degree isotherm from above";
        String units "m";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    fog_area_fraction {
        Float32 _FillValue 9.96921E36;
        String long_name "Fog";
        String metno_name "fog_area_fraction";
        String units "1";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    SFX_TICE_01 {
        String standard_name "sea_ice_temperature";
        String long_name "Sea_ice_temperature_in_layer_1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_TICE_02 {
        String standard_name "sea_ice_temperature";
        String long_name "Sea_ice_temperature_in_layer_2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_TICE_03 {
        String standard_name "sea_ice_temperature";
        String long_name "Sea_ice_temperature_in_layer_3";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_TICE_04 {
        String standard_name "sea_ice_temperature";
        String long_name "Sea_ice_temperature_in_layer_4";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_SIC {
        String standard_name "sea_ice_area_fraction";
        String long_name "Sea_ice_fraction";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    SFX_SST {
        String units "K";
        String standard_name "sea_surface_temperature";
        String long_name "Sea Surface Temperature (SST)";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1, 1069, 949;
    }
    SFX_TS_WATER {
        String units "K";
        Float32 _FillValue 9.96921E36;
        String long_name "Surface temperature for inland water tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T_SNOW {
        String units "K";
        String long_name "Snow temperature for snow in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T_ICE {
        String units "K";
        String long_name "Ice temperature in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T_MNW {
        String units "K";
        String long_name "Mean water temperature in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T_WML {
        String units "K";
        String long_name "Mixed layer temperature in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T_BOT {
        String units "K";
        String long_name "Bottom water temperature in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_H_SNOW {
        String units "m";
        String long_name "Snow thickness over lakes in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_H_ICE {
        String units "m";
        String long_name "Ice thickness over lakes in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_H_ML {
        String units "m";
        String long_name "Mixed layer depth in FLAKE";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001TG1 {
        String units "K";
        String standard_name "soil_temperature";
        String long_name "Soil temperature layer 1 for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002TG1 {
        String units "K";
        String standard_name "soil_temperature";
        String long_name "Soil temperature layer 1 for patch 2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001TG2 {
        String units "K";
        String standard_name "soil_temperature";
        String long_name "Soil temperature layer 2 for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002TG2 {
        String units "K";
        String standard_name "soil_temperature";
        String long_name "Soil_temp_layer_2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001WG1 {
        String units "m3/m3";
        String long_name "Soil moisture layer 1 for nature tile for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002WG1 {
        String units "m3/m3";
        String long_name "Soil moisture later 1 for nature tile for patch 2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001WG2 {
        String units "m3/m3";
        String long_name "Soil moisture layer 2 for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002WG2 {
        String units "m3/m3";
        String long_name "Soil moisture layer 2 for patch 2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001WGI1 {
        String units "m3/m3";
        String long_name "Soil ice in layer 1 for patch 1 for nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002WGI1 {
        String units "m3/m3";
        String long_name "Soil ice layer 1 for patch 2 for nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001WGI2 {
        String units "m3/m3";
        String long_name "Soil ice layer 2 for patch 1 for nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002WGI2 {
        String units "m3/m3";
        String long_name "Soil ice layer 2 for patch 2 for nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001WSN_VEG1 {
        String units "kg/m2";
        String standard_name "liquid_water_content_of_surface_snow";
        String long_name "Snow Water Equivalent layer 1 for patch 1 on nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002WSN_VEG1 {
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        String units "kg/m2";
        String standard_name "liquid_water_content_of_surface_snow";
        String long_name "Snow Water Equivalent layer 1 for patch 2 on nature tile";
        Float32 _FillValue 9.96921E36;
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001RSN_VEG1 {
        String units "kg/m3";
        String standard_name "snow_density";
        String long_name "Snow_density_layer_1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002RSN_VEG1 {
        String units "kg/m3";
        String standard_name "snow_density";
        String long_name "Snow_density_layer_1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001ASN_VEG {
        String units "1";
        String long_name "Snow_albedo";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002ASN_VEG {
        String units "1";
        String long_name "Snow_albedo";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_WS_ROAD {
        Float32 _FillValue 9.96921E36;
        String long_name "Road water reservoir";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T2M_SEA {
        String units "K";
        String long_name "Screen level temperature for sea tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Q2M_SEA {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for sea tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HU2M_SEA {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for sea tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_ZON10M_SEA {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level zonal wind for sea tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_MER10M_SEA {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level meridional wind for sea tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T2M_WAT {
        String units "K";
        String long_name "Screen level temperature for water tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Q2M_WAT {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for inland water tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HU2M_WAT {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for inland water tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_ZON10M_WAT {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level zonal wind for inland water tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_MER10M_WAT {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level meridional wind for inland water tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_TALB_ISBA {
        String units "1";
        String long_name "Surface_total_albedo";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T2M_ISBA {
        String units "K";
        String long_name "Screen level temperature for nature tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Q2M_ISBA {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HU2M_ISBA {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_ZON10M_ISBA {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of zonal wind for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_MER10M_ISBA {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of meridional wind for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001T2M_P {
        String units "K";
        String standard_name "air_temperature";
        String long_name "Screen level temperature for patch 1 for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002T2M_P {
        String units "K";
        String standard_name "air_temperature";
        String long_name "Screen level temperature for patch 2 for nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001Q2M_P {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for nature tile for patch 1";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002Q2M_P {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for nature tile for patch 2";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001HU2M_P {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for nature tile for patch 1";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002HU2M_P {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for nature tile for patch 2";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001ZON10M_P {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of zonal wind for nature tile for patch 1";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001MER10M_P {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of meridional wind for nature tile for patch 1";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002ZON10M_P {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of zonal wind for nature tile for patch 2";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002MER10M_P {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of meridional wind for nature tile for patch 2";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_RNC_ISBA {
        String units "W/m2";
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated surface net radiation for the nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HC_ISBA {
        String units "W/m2";
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated sensible heat flux for the nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_LEC_ISBA {
        String units "W/m2";
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated latent heat flux for the nature tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_FMUC_ISBA {
        String units "kg/ms2";
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated screen level zonal wind stress";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_FMVC_ISBA {
        String units "kg/ms2";
        Float32 _FillValue 9.96921E36;
        String long_name "Accumulated meridional level zonal wind stress";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_PSNG_ISBA {
        String units "1";
        String long_name "Snow_frac_over_ground";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_PSNV_ISBA {
        String units "1";
        String long_name "Snow_frac_over_veg";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_PSN_ISBA {
        String units "1";
        String standard_name "surface_snow_area_fraction";
        String long_name "Snow_fraction";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_WSN_T_ISBA {
        String units "kg/m2";
        String standard_name "liquid_water_content_of_surface_snow";
        String long_name "Snow Water Equivalent Total";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_DSN_T_ISBA {
        String units "m";
        String long_name "Snow depth";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001LAI {
        String long_name "Leaf Area Index for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002LAI {
        String long_name "Leaf Area Index for patch 2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X001VEG {
        String units "1";
        String long_name "Nature vegetation fraction for patch 1";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_X002VEG {
        String units "1";
        String long_name "Nature vegetation fraction for patch 2";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T2M_TEB {
        String units "K";
        String long_name "Screen level temperature for town tile";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Q2M_TEB {
        String units "kg/kg";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level specific humidity for town tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HU2M_TEB {
        String units "1";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level relative humidity for town tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_ZON10M_TEB {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of zonal wind for town tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_MER10M_TEB {
        String units "m/s";
        Float32 _FillValue 9.96921E36;
        String long_name "Screen level of meridional wind for town tile";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_RI {
        String long_name "Averaged richardson number";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_TS {
        String units "K";
        String standard_name "air_temperature";
        String long_name "Surface temperature (T0M)";
        Float32 _FillValue 9.96921E36;
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_EMIS {
        String units "1";
        String long_name "Surface emissivity";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_T2M {
        String units "K";
        String standard_name "air_temperature";
        String long_name "Screen level temperature";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Q2M {
        String units "kg/kg";
        String long_name "Screen level specific humidity";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_HU2M {
        String units "1";
        String long_name "Screen level relative humidity";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_ZON10M {
        String units "m/s";
        String long_name "Screen level zonal wwind";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_MER10M {
        String units "m/s";
        String long_name "Screen level meridional wind";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_RN {
        String units "W/m2";
        String long_name "Averaged net radiation";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_H {
        String units "W/m2";
        String standard_name "surface_upward_sensible_heat_flux";
        String long_name "Averaged sensible heat flux";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_LE {
        String units "W/m2";
        String standard_name "surface_upward_latent_heat_flux";
        String long_name "Averaged total latent heat flux";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_GFLUX {
        String units "W/m2";
        String long_name "Averaged ground heat flux";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_FMU {
        String units "kg/ms2";
        String long_name "Averaged screen level zonal wind stress";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_FMV {
        String units "kg/ms2";
        String long_name "Averaged meridional wind stress";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_CD {
        String units "W/s2";
        String long_name "Drag coefficient for momentum";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_CH {
        String units "W/s";
        String long_name "Drag coefficient for heat";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_CE {
        String units "W/s/K";
        String long_name "Drag coefficient for evaporation";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Z0 {
        String units "m";
        String long_name "Roughness length for momentum";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    SFX_Z0H {
        String units "m";
        String long_name "Roughness Length For Heat";
        String institution "MetCoOp";
        String model "Variable from the External Surface model SURFEX";
        String comment "Variable is named as in source code but with the prefix SFX_";
        String references "https://www.umr-cnrm.fr/surfex/";
        String grid_mapping "projection_lambert";
        String coordinates "longitude latitude";
        UInt32 _ChunkSizes 1, 1069, 949;
    }
    NC_GLOBAL {
        String Conventions "CF-1.6";
        String institution "Norwegian Meteorological Institute, MET Norway";
        String creator_url "met.no";
        String source "MEPS 2.5km";
        String min_time "2026-11-28 23:00:00Z";
        String max_time "2026-11-28";
        String geospatial_lat_min "49.8";
        String geospatial_lat_max "75.2";
        String geospatial_lon_min "-18.1";
        String geospatial_lon_max "54.2";
        String references "unknown";
        String license "https://www.met.no/en/free-meteorological-data/Licensing-and-crediting";
        String comment "For more information, please visit https://github.com/metno/NWPdocs/wiki";
        String history "2026-11-26T08:21:33 creation by fimex";
    }
}

cmake_minimum_required(VERSION 3.5)

project(jetracer_fleet)

find_package(ament_cmake REQUIRED)

install(DIRECTORY
  maps/
  DESTINATION share/${PROJECT_NAME}/maps
)

# Same pattern as free_fleet_examples: regenerate the nav graph from the
# .building.yaml as a normal build artifact, every colcon build.
file(GLOB_RECURSE traffic_editor_paths "maps/*.building.yaml")

foreach(path ${traffic_editor_paths})
  string(REGEX REPLACE "\\.[^.]*\.[^.]*$" "" no_extension_path ${path})
  string(REGEX MATCH "[^\/]+$" world_name ${no_extension_path})

  set(map_path ${path})
  set(output_world_name ${world_name})
  set(output_dir ${CMAKE_CURRENT_BINARY_DIR}/maps/${output_world_name})
  set(output_nav_graphs_dir ${output_dir}/nav_graphs/)
  set(output_nav_graphs_phony ${output_nav_graphs_dir}/phony)

  add_custom_command(
    OUTPUT ${output_nav_graphs_phony}
    COMMAND ros2 run rmf_building_map_tools building_map_generator nav ${map_path} ${output_nav_graphs_dir}
    DEPENDS ${map_path}
  )

  add_custom_target(generate_${output_world_name}_nav_graphs ALL
    DEPENDS ${output_nav_graphs_phony}
  )

  install(
    DIRECTORY ${output_dir}
    DESTINATION share/${PROJECT_NAME}/maps
  )
endforeach()

# Includes config/rmf_web/jetracer_api_server_config.py, which the natively-run
# rmf-web api-server is pointed at via RMF_API_SERVER_CONFIG.
install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config
)

install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)


# Docker builds use the standalone repository root as their source context.
# Run Compose from that source tree, rather than from this installed copy.
install(DIRECTORY
  docker/
  DESTINATION share/${PROJECT_NAME}/docker
  PATTERN ".env" EXCLUDE
)

# PROGRAMS, not FILES -- FILES drops the executable bit, and `ros2 launch`
# reports that as "executable 'jetracer_fleet_adapter.py' not found", which is
# a confusing way to say chmod. Same failure mode already documented for
# free_fleet's own fleet_adapter.py in jetracer-real-robot-e2e-flow.md.
install(PROGRAMS
  scripts/jetracer_fleet_adapter.py
  scripts/jetracer_onboarding.py
  scripts/jetracer_rmf_web.sh
  DESTINATION lib/${PROJECT_NAME}
)

# Custom rmf-web dashboard sources (main.tsx / index.html) plus the build script.
# PROGRAMS for the whole directory would mark the .tsx executable, so the script
# is installed separately with its bit preserved.
install(DIRECTORY
  dashboard/
  DESTINATION share/${PROJECT_NAME}/dashboard
  PATTERN "build_jetracer_dashboard.sh" EXCLUDE
)
install(PROGRAMS
  dashboard/build_jetracer_dashboard.sh
  DESTINATION share/${PROJECT_NAME}/dashboard
)

ament_package()

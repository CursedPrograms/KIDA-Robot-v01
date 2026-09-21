! map_accumulate.f90 — pixel+depth -> 3D world point projection, plus
! voxel-grid binning, called from mapper/build_3d_map.py via ctypes.
!
! Fortran's actual job in this pipeline: the array-heavy numeric part —
! projecting every depth-map pixel into a 3D point and deduplicating
! points that land in the same voxel cell (so a 256x320 depth map doesn't
! turn into 80,000 near-duplicate points per frame). HailoRT itself is
! only reachable from Python/C++, so the depth *inference* stays in
! mapper/build_3d_map.py — this module only does the geometry after.
!
! Projection is a simplified pinhole approximation (equal horizontal/
! vertical FOV, no lens distortion, no real calibrated intrinsics — this
! robot doesn't have those) using ray angles derived from pixel position
! and the given field-of-view. Good enough for a "cheap" map, not
! survey-grade.

module map_accumulate
  use, intrinsic :: iso_c_binding
  implicit none
contains

  ! Project one batch of (u, v, depth_rel) pixel samples into world-frame
  ! (x, y, z) centimeters, given the camera's assumed horizontal FOV, the
  ! robot's pose (pose_x_cm, pose_y_cm, heading_deg), and a depth scale
  ! (cm per unit of the model's relative depth output — the caller derives
  ! this by matching the depth map against a real ultrasonic/laser
  ! reading at a known pixel, since monocular depth models give relative,
  ! not metric, depth on their own).
  subroutine project_points(n, u, v, depth_rel, img_w, img_h, &
                             hfov_deg, scale_cm, &
                             pose_x_cm, pose_y_cm, heading_deg, &
                             out_x, out_y, out_z) bind(c, name="project_points")
    integer(c_int), intent(in), value :: n, img_w, img_h
    integer(c_int), intent(in) :: u(n), v(n)
    real(c_double), intent(in) :: depth_rel(n)
    real(c_double), intent(in), value :: hfov_deg, scale_cm
    real(c_double), intent(in), value :: pose_x_cm, pose_y_cm, heading_deg
    real(c_double), intent(out) :: out_x(n), out_y(n), out_z(n)

    real(c_double), parameter :: PI = 3.14159265358979323846d0
    real(c_double) :: hfov_rad, vfov_deg, vfov_rad
    real(c_double) :: theta, phi, forward_cm, x_cam, y_cam, z_cam
    real(c_double) :: heading_rad, world_x, world_y
    integer :: i

    hfov_rad = hfov_deg * PI / 180.0d0
    vfov_deg = hfov_deg * real(img_h, c_double) / real(img_w, c_double)
    vfov_rad = vfov_deg * PI / 180.0d0
    heading_rad = heading_deg * PI / 180.0d0

    do i = 1, n
      theta = (real(u(i), c_double) - real(img_w, c_double) / 2.0d0) &
              / real(img_w, c_double) * hfov_rad
      phi   = (real(v(i), c_double) - real(img_h, c_double) / 2.0d0) &
              / real(img_h, c_double) * vfov_rad

      forward_cm = depth_rel(i) * scale_cm
      x_cam = forward_cm * tan(theta)   ! right-positive, camera frame
      y_cam = forward_cm * tan(phi)     ! down-positive, camera frame
      z_cam = forward_cm                ! forward, camera frame

      ! Rotate camera-frame (x_cam, z_cam) into world-frame by the robot's
      ! heading, then translate by its position. y_cam (vertical) is left
      ! untouched — the robot doesn't roll/pitch in this model.
      world_x = pose_x_cm + x_cam * cos(heading_rad) + z_cam * sin(heading_rad)
      world_y = pose_y_cm - x_cam * sin(heading_rad) + z_cam * cos(heading_rad)

      out_x(i) = world_x
      out_y(i) = world_y
      out_z(i) = y_cam
    end do
  end subroutine project_points

  ! Voxel-grid downsample: bins n (x,y,z) points into voxel_cm cells and
  ! returns one representative point per occupied cell (its centroid).
  ! out_x/out_y/out_z must be sized >= n on entry; out_count on return is
  ! how many of those slots were actually used.
  subroutine voxel_bin(n, x, y, z, voxel_cm, out_x, out_y, out_z, out_count) &
      bind(c, name="voxel_bin")
    integer(c_int), intent(in), value :: n
    real(c_double), intent(in) :: x(n), y(n), z(n)
    real(c_double), intent(in), value :: voxel_cm
    real(c_double), intent(out) :: out_x(n), out_y(n), out_z(n)
    integer(c_int), intent(out) :: out_count

    integer(c_int), allocatable :: key_i(:), key_j(:), key_k(:)
    real(c_double), allocatable :: sum_x(:), sum_y(:), sum_z(:)
    integer(c_int), allocatable :: cell_count(:)
    integer :: i, ci, cj, ck, m, found, cells
    logical :: matched

    allocate(key_i(n), key_j(n), key_k(n))
    allocate(sum_x(n), sum_y(n), sum_z(n), cell_count(n))
    cells = 0

    do i = 1, n
      ci = nint(x(i) / voxel_cm)
      cj = nint(y(i) / voxel_cm)
      ck = nint(z(i) / voxel_cm)

      matched = .false.
      do m = 1, cells
        if (key_i(m) == ci .and. key_j(m) == cj .and. key_k(m) == ck) then
          sum_x(m) = sum_x(m) + x(i)
          sum_y(m) = sum_y(m) + y(i)
          sum_z(m) = sum_z(m) + z(i)
          cell_count(m) = cell_count(m) + 1
          matched = .true.
          exit
        end if
      end do

      if (.not. matched) then
        cells = cells + 1
        key_i(cells) = ci; key_j(cells) = cj; key_k(cells) = ck
        sum_x(cells) = x(i); sum_y(cells) = y(i); sum_z(cells) = z(i)
        cell_count(cells) = 1
      end if
    end do

    do m = 1, cells
      out_x(m) = sum_x(m) / real(cell_count(m), c_double)
      out_y(m) = sum_y(m) / real(cell_count(m), c_double)
      out_z(m) = sum_z(m) / real(cell_count(m), c_double)
    end do
    out_count = cells

    deallocate(key_i, key_j, key_k, sum_x, sum_y, sum_z, cell_count)
  end subroutine voxel_bin

end module map_accumulate

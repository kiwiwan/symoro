# -*- coding: utf-8 -*-


from copy import copy

import sympy
from sympy import Matrix

from pysymoro.geometry import compute_screw_transform
from pysymoro.geometry import compute_rot_trans
from pysymoro.kinematics import compute_vel_acc
from pysymoro.kinematics import compute_omega
from symoroutils import tools
from symoroutils.paramsinit import ParamsInit


def inertia_spatial(inertia, ms_tensor, mass):
    """
    Compute spatial inertia matrix (internal function).
    """
    return Matrix([
        (mass * sympy.eye(3)).row_join(tools.skew(ms_tensor).transpose()),
        tools.skew(ms_tensor).row_join(inertia)
    ])


def compute_torque(robo, symo, j, jaj, react_wrench, torque):
    """
    Compute torque (internal function).

    Note:
        torque is the output parameter.
    """
    if robo.sigma[j] == 2:
        tau_total = 0
    else:
        tau = react_wrench[j].transpose() * jaj[j]
        fric_rotor = robo.fric_s(j) + robo.fric_v(j) + robo.tau_ia(j)
        tau_total = tau[0, 0] + fric_rotor
    torque[j] = symo.replace(tau_total, 'GAM', j, forced=True)


def compute_joint_torque(robo, symo, j, Fjnt, Njnt, torque):
    """
    Compute actuator torques - projection of joint wrench on the joint
    axis (internal function).

    Note:
        torque is the output parameter.
    """
    if robo.sigma[j] == 2:
        tau_total = 0
    else:
        tau = (robo.sigma[j] * Fjnt[j]) + ((1 - robo.sigma[j]) * Njnt[j])
        fric_rotor = robo.fric_s(j) + robo.fric_v(j) + robo.tau_ia(j)
        tau_total = tau[2] + fric_rotor
    torque[j] = symo.replace(tau_total, 'GAM', j, forced=True)


def compute_dynamic_wrench(robo, symo, j, w, wdot, U, vdot, F, N):
    """
    Compute total wrench of link j (internal function).

    Note:
        F, N are the output parameters
    """
    F[j] = (robo.M[j] * vdot[j]) + (U[j] * robo.MS[j])
    F[j] = symo.mat_replace(F[j], 'F', j)
    Psi = robo.J[j] * w[j]
    Psi = symo.mat_replace(Psi, 'PSI', j)
    N[j] = (robo.J[j] * wdot[j]) + (tools.skew(w[j]) * Psi)
    N[j] = symo.mat_replace(N[j], 'No', j)


def compute_joint_wrench(
    robo, symo, j, antRj, antPj, vdot, F, N, Fjnt, Njnt, Fex, Nex
):
    """
    Compute reaction wrench (for default Newton-Euler) of joint j
    (internal function).

    Note:
        Fjnt, Njnt, Fex, Nex are the output parameters
    """
    forced = True if j == 0 else False
    i = robo.ant[j]
    Fjnt[j] = F[j] + Fex[j]
    Fjnt[j] = symo.mat_replace(Fjnt[j], 'E', j, forced=forced)
    Njnt[j] = N[j] + Nex[j] + (tools.skew(robo.MS[j]) * vdot[j])
    Njnt[j] = symo.mat_replace(Njnt[j], 'N', j, forced=forced)
    f_ant = antRj[j] * Fjnt[j]
    f_ant = symo.mat_replace(f_ant, 'FDI', j)
    if i != -1:
        Fex[i] = Fex[i] + f_ant
        Nex[i] = Nex[i] + \
            (antRj[j] * Njnt[j]) + (tools.skew(antPj[j]) * f_ant)


def compute_beta(robo, symo, j, w, beta):
    """
    Compute beta wrench which is a combination of coriolis forces,
    centrifugal forces and external forces (internal function).

    Note:
        beta is the output parameter
    """
    expr1 = robo.J[j] * w[j]
    expr1 = symo.mat_replace(expr1, 'JW', j)
    expr2 = tools.skew(w[j]) * expr1
    expr2 = symo.mat_replace(expr2, 'KW', j)
    expr3 = tools.skew(w[j]) * robo.MS[j]
    expr4 = tools.skew(w[j]) * expr3
    expr4 = symo.mat_replace(expr4, 'SW', j)
    expr5 = -robo.Nex[j] - expr2
    expr6 = -robo.Fex[j] - expr4
    beta[j] = Matrix([expr6, expr5])
    beta[j] = symo.mat_replace(beta[j], 'BETA', j)


def compute_gamma(robo, symo, j, antRj, antPj, w, wi, gamma):
    """
    Compute gyroscopic acceleration (internal function).

    Note:
        gamma is the output parameter
    """
    i = robo.ant[j]
    expr1 = tools.skew(wi[j]) * Matrix([0, 0, robo.qdot[j]])
    expr1 = symo.mat_replace(expr1, 'WQ', j)
    expr2 = (1 - robo.sigma[j]) * expr1
    expr3 = 2 * robo.sigma[j] * expr1
    expr4 = tools.skew(w[i]) * antPj[j]
    expr5 = tools.skew(w[i]) * expr4
    expr6 = antRj[j].transpose() * expr5
    expr7 = expr6 + expr3
    expr7 = symo.mat_replace(expr7, 'LW', j)
    gamma[j] = Matrix([expr7, expr2])
    gamma[j] = symo.mat_replace(gamma[j], 'GYACC', j)


def compute_zeta(robo, symo, j, gamma, jaj, zeta, qddot=None):
    """
    Compute relative acceleration (internal function).

    Note:
        zeta is the output parameter
    """
    if qddot == None:
        qddot = robo.qddot
    expr = gamma[j] + (qddot[j] * jaj[j])
    zeta[j] = symo.mat_replace(expr, 'ZETA', j)


def compute_composite_inertia(
    robo, symo, j, antRj, antPj,
    comp_inertia3, comp_ms, comp_mass, composite_inertia
):
    """
    Compute composite inertia (internal function).

    Note:
        comp_inertia3, comp_ms, comp_mass, composite_inertia are the
        output parameters.
    """
    i = robo.ant[j]
    i_ms_j_c = antRj[j] * comp_ms[j]
    i_ms_j_c = symo.mat_replace(i_ms_j_c, 'AS', j)
    expr1 = antRj[j] * comp_inertia3[j]
    expr1 = symo.mat_replace(expr1, 'AJ', j)
    expr2 = expr1 * antRj[j].transpose()
    expr2 = symo.mat_replace(expr2, 'AJA', j)
    expr3 = tools.skew(antPj[j]) * tools.skew(i_ms_j_c)
    expr3 = symo.mat_replace(expr3, 'PAS', j)
    comp_inertia3[i] += expr2 - (expr3 + expr3.transpose()) + \
        (comp_mass[j] * tools.skew(antPj[j]) * \
        tools.skew(antPj[j]).transpose())
    comp_ms[i] = comp_ms[i] + i_ms_j_c + (antPj[j] * comp_mass[j])
    comp_mass[i] = comp_mass[i] + comp_mass[j]
    composite_inertia[i] = inertia_spatial(
        comp_inertia3[i], comp_ms[i], comp_mass[i]
    )


def compute_composite_beta(
    robo, symo, j, jTant, zeta, composite_inertia, composite_beta
):
    """
    Compute composite beta (internal function).

    Note:
        composite_beta is the output parameter
    """
    i = robo.ant[j]
    expr1 = composite_inertia[j] * zeta[j]
    expr1 = symo.mat_replace(expr1, 'IZ', j)
    expr2 = jTant[j].transpose() * expr1
    expr2 = symo.mat_replace(expr2, 'SIZ', j)
    expr3 = jTant[j].transpose() * composite_beta[j]
    expr3 = symo.mat_replace(expr3, 'SBE', j)
    composite_beta[i] = composite_beta[i] + expr3 - expr2


def replace_composite_terms(
    symo, grandJ, beta, j, composite_inertia,
    composite_beta, replace=False
):
    """
    Replace composite inertia and beta (internal function).

    Note:
        composite_inertia are composite_beta are the output parameters
    """
    forced = False
    if replace and j == 0: forced = False
    composite_inertia[j] = symo.mat_replace(
        grandJ[j], 'MJE', j, symmet=True, forced=forced
    )
    composite_beta[j] = symo.mat_replace(
        beta[j], 'VBE', j, forced=forced
    )


def replace_star_terms(
    symo, grandJ, beta, j, star_inertia, star_beta, replace=False
):
    """
    Replace star inertia and beta (internal function).

    Note:
        star_inertia are star_beta are the output parameters
    """
    forced = False
    if replace and j == 0: forced = False
    star_inertia[j] = symo.mat_replace(
        grandJ[j], 'MJE', j, symmet=True, forced=forced
    )
    star_beta[j] = symo.mat_replace(beta[j], 'VBE', j, forced=forced)


def compute_composite_terms(
    robo, symo, j, jTant, zeta,
    composite_inertia, composite_beta
):
    """
    Compute composite inertia and beta (internal function).

    Note:
        composite_inertia are composite_beta are the output parameters
    """
    i = robo.ant[j]
    expr1 = jTant[j].transpose() * composite_inertia[j]
    expr1 = symo.mat_replace(expr1, 'GX', j)
    expr2 = expr1 * jTant[j]
    expr2 = symo.mat_replace(expr2, 'TKT', j, symmet=True)
    expr3 = expr1 * zeta[j]
    expr3 = symo.mat_replace(expr3, 'SIZ', j)
    expr4 = jTant[j].transpose() * composite_beta[j]
    expr4 = symo.mat_replace(expr4, 'SBE', j)
    composite_inertia[i] = composite_inertia[i] + expr2
    composite_beta[i] = composite_beta[i] + expr4 - expr3


def compute_hinv(
    robo, symo, j, jaj, star_inertia, jah, h_inv, flex=False
):
    """
    Note:
        h_inv and jah are the output parameters
    """
    inertia_jaj = star_inertia[j] * jaj[j]
    inertia_jaj = symo.mat_replace(inertia_jaj, 'JA', j)
    h = jaj[j].dot(inertia_jaj)
    if not flex:
        h = h + robo.IA[j]
    h_inv[j] = 1 / h
    h_inv[j] = symo.replace(h_inv[j], 'JD', j)
    jah[j] = inertia_jaj * h_inv[j]
    jah[j] = symo.mat_replace(jah[j], 'JU', j)


def compute_tau(robo, symo, j, jaj, star_beta, tau, flex=False):
    """
    Note:
        tau is the output parameter
    """
    if robo.sigma[j] == 2:
        tau[j] = 0
    else:
        if flex:
            joint_friction = 0
        else:
            joint_friction = robo.fric_s(j) + robo.fric_v(j)
        tau[j] = jaj[j].dot(star_beta[j]) + robo.GAM[j] - joint_friction
    tau[j] = symo.replace(tau[j], 'GW', j)


def compute_star_terms(
    robo, symo, j, jaj, jTant, gamma, tau,
    h_inv, jah, star_inertia, star_beta, flex=False
):
    """
    Note:
        h_inv, jah, star_inertia, star_beta are the output parameters
    """
    i = robo.ant[j]
    inertia_jaj = star_inertia[j] * jaj[j]
    inertia_jaj = symo.mat_replace(inertia_jaj, 'JA', j)
    h = jaj[j].dot(inertia_jaj)
    if not flex:
        h = h + robo.IA[j]
    if not flex or robo.eta[j]:
        h_inv[j] = 1 / h
        h_inv[j] = symo.replace(h_inv[j], 'JD', j)
        jah[j] = inertia_jaj * h_inv[j]
        jah[j] = symo.mat_replace(jah[j], 'JU', j)
        k_inertia = star_inertia[j] - (jah[j] * inertia_jaj.transpose())
        k_inertia = symo.mat_replace(k_inertia, 'GK', j)
    else:
        k_inertia = star_inertia[j]
    expr1 = k_inertia * gamma[j]
    expr1 = symo.mat_replace(expr1, 'NG', j)
    if not flex or robo.eta[j]:
        expr2 = expr1 + (jah[j] * tau[j])
    else:
        expr2 = expr1 + (star_inertia[j] * jaj[j] * robo.qddot[j])
    expr2 = symo.mat_replace(expr2, 'VS', j)
    alpha = expr2 - star_beta[j]
    alpha = symo.mat_replace(alpha, 'AP', j)
    expr3 = jTant[j].transpose() * k_inertia
    expr3 = symo.mat_replace(expr3, 'GX', j)
    expr4 = expr3 * jTant[j]
    expr4 = symo.mat_replace(expr4, 'TKT', j, symmet=True)
    star_inertia[i] = star_inertia[i] + expr4
    star_beta[i] = star_beta[i] - (jTant[j].transpose() * alpha)


def compute_joint_accel(
    robo, symo, j, jaj, jTant, h_inv, jah, gamma,
    tau, grandVp, star_beta, star_inertia, qddot
):
    """
    Compute joint acceleration (internal function)

    Note:
        qddot is the output parameter
    """
    i = robo.ant[j]
    expr1 = (jTant[j] * grandVp[i]) + gamma[j]
    expr1 = symo.mat_replace(expr1, 'VR', j)
    expr2 = jah[j].dot(expr1)
    expr2 = symo.replace(expr2, 'GU', j)
    if robo.sigma[j] == 2:
        qddot[j] = 0
    else:
        qddot[j] = (h_inv[j] * tau[j]) - expr2
    qddot[j] = symo.replace(qddot[j], 'QDP', j, forced=True)


def compute_link_accel(robo, symo, j, jTant, zeta, grandVp):
    """
    Compute link acceleration (internal function).

    Note:
        grandVp is the output parameter
    """
    i = robo.ant[j]
    grandVp[j] = (jTant[j] * grandVp[i]) + zeta[j]
    grandVp[j][:3, 0] = symo.mat_replace(grandVp[j][:3, 0], 'VP', j)
    grandVp[j][3:, 0] = symo.mat_replace(grandVp[j][3:, 0], 'WP', j)


def write_numerical_inverse(symo, inertia, symmet=False):
    """
    Write the inverse for the inertia matrix (6x6) to be computed
    numerically using numpy in the output file.
    """
    # write strating comments
    symo.write_line("# NUMERICAL INVERSION OF INERTIA MATRIX - START")
    symo.write_line("# REQUIRES numpy")
    # setup matrix numMJE0
    symo.write_line("# setup matrix in numpy format")
    symo.write_equation('numMJE0', 'numpy.zeros((6, 6))')
    for i in xrange(inertia.rows):
        for j in xrange(inertia.cols):
            if inertia[i, j] != 0:
                symo.write_equation(
                    'numMJE0[{row}, {col}]'.format(row=i, col=j),
                    str(inertia[i, j])
                )
    # numInvMJE0 = numpy.linalg.inv(numMJE0)
    symo.write_line("# invert matrix")
    symo.write_line(
        "# In Matlab this can be performed without matrix inverse"
    )
    symo.write_line("# VP0 = numMJE0 \ BETA0")
    symo.write_equation('numInvMJE0', 'numpy.linalg.inv(numMJE0)')
    # assign elements of the inverted matrix
    symo.write_line("# assign each element of the inverted (symmetric)")
    symo.write_line("# matrix to be compatible with future computation")
    for i in xrange(inertia.rows):
        for j in xrange(inertia.cols):
            if symmet and i < j:
                continue
            symo.write_equation(
                'InvMJE{row}{col}0'.format(row=i+1, col=j+1),
                'numInvMJE0[{row}, {col}]'.format(row=i, col=j)
            )
    # write ending comments
    symo.write_line("# NUMERICAL INVERSION OF INERTIA MATRIX - END")


def get_numerical_inverse_out(inertia, symmet=False):
    """
    Return the inverse of the matrix as formed by strings.
    """
    inv_inertia = sympy.zeros(inertia.rows, inertia.cols)
    for j in xrange(inertia.cols):
        for i in xrange(inertia.rows):
            if symmet and i < j:
                inv_inertia[i, j] = inv_inertia[j, i]
                continue
            inv_inertia[i, j] = sympy.var(
                'InvMJE{row}{col}0'.format(row=i+1, col=j+1)
            )
    return inv_inertia


def compute_base_accel(robo, symo, star_inertia, star_beta, grandVp):
    """
    Compute base acceleration (internal function).

    Note:
        grandVp is the output parameter
    """
    forced = False
    grandVp[0] = Matrix([robo.vdot0 - robo.G, robo.w0])
    if robo.is_floating:
        forced = True
        symo.flushout()
        write_numerical_inverse(symo, star_inertia[0], symmet=True)
        inv_base_star_inertia = get_numerical_inverse_out(
            star_inertia[0], symmet=True
        )
        grandVp[0] = inv_base_star_inertia * star_beta[0]
    grandVp[0][:3, 0] = symo.mat_replace(
        grandVp[0][:3, 0], 'VP', 0, forced=forced
    )
    grandVp[0][3:, 0] = symo.mat_replace(
        grandVp[0][3:, 0], 'WP', 0, forced=forced
    )


def compute_base_accel_composite(
    robo, symo, composite_inertia, composite_beta, grandVp
):
    """
    Compute base acceleration when using composite inertia matrix
    (internal function).

    Note:
        grandVp is the output parameter
    """
    forced = False
    grandVp[0] = Matrix([robo.vdot0 - robo.G, robo.w0])
    if robo.is_floating:
        forced = True
        symo.flushout()
        write_numerical_inverse(symo, composite_inertia[0], symmet=True)
        inv_base_comp_inertia = get_numerical_inverse_out(
            composite_inertia[0], symmet=True
        )
        grandVp[0] = inv_base_comp_inertia * composite_beta[0]
    grandVp[0][:3, 0] = symo.mat_replace(
       grandVp[0][:3, 0], 'VP', 0, forced=forced
    )
    grandVp[0][3:, 0] = symo.mat_replace(
        grandVp[0][3:, 0], 'WP', 0, forced=forced
    )


def compute_reaction_wrench(
    robo, symo, j, grandVp, inertia, beta_wrench, react_wrench
):
    """
    Compute reaction wrench (internal function).

    Note:
        react_wrench is the output parameter
    """
    expr = inertia[j] * grandVp[j]
    expr = symo.mat_replace(expr, 'DY', j)
    wrench = expr - beta_wrench[j]
    react_wrench[j][:3, 0] = symo.mat_replace(wrench[:3, 0], 'E', j)
    react_wrench[j][3:, 0] = symo.mat_replace(wrench[3:, 0], 'N', j)


def fixed_inverse_dynmodel(robo, symo):
    """
    Compute the Inverse Dynamic Model using Newton-Euler algorithm for
    tree structure robots with fixed base.

    Parameters:
        robo: Robot - instance of robot description container
        symo: symbolmgr.SymbolManager - instance of symbolic manager
    """
    # init external forces
    Fex = copy(robo.Fex)
    Nex = copy(robo.Nex)
    # init transformation
    antRj, antPj = compute_rot_trans(robo, symo)
    # init velocities and accelerations
    w, wdot, vdot, U = compute_vel_acc(robo, symo, antRj, antPj)
    # init forces vectors
    F = ParamsInit.init_vec(robo)
    N = ParamsInit.init_vec(robo)
    Fjnt = ParamsInit.init_vec(robo)
    Njnt = ParamsInit.init_vec(robo)
    # init torque list
    torque = ParamsInit.init_scalar(robo)
    for j in xrange(1, robo.NL):
        compute_dynamic_wrench(robo, symo, j, w, wdot, U, vdot, F, N)
    for j in reversed(xrange(1, robo.NL)):
        compute_joint_wrench(
            robo, symo, j, antRj, antPj, vdot,
            F, N, Fjnt, Njnt, Fex, Nex
        )
    for j in xrange(1, robo.NL):
        compute_joint_torque(robo, symo, j, Fjnt, Njnt, torque)


def mobile_inverse_dynmodel(robo, symo):
    """
    Compute the Inverse Dynamic Model using Newton-Euler algorithm for
    mobile robots.

    Parameters:
        robo: Robot - instance of robot description container
        symo: symbolmgr.SymbolManager - instance of symbol manager
    """
    # init external forces
    Fex = copy(robo.Fex)
    Nex = copy(robo.Nex)
    # init transformation
    antRj, antPj = compute_rot_trans(robo, symo)
    # init velocities and accelerations
    w, wdot, vdot, U = compute_vel_acc(robo, symo, antRj, antPj)
    dv0 = ParamsInit.product_combinations(robo.w0)
    symo.mat_replace(dv0, 'DV', 0)
    hatw_hatw = sympy.Matrix([
        [-dv0[3]-dv0[5], dv0[1], dv0[2]],
        [dv0[1], -dv0[5]-dv0[0], dv0[4]],
        [dv0[2], dv0[4], -dv0[3]-dv0[0]]
    ])
    U[0] = hatw_hatw + tools.skew(robo.wdot0)
    symo.mat_replace(U[0], 'U', 0)
    # init forces vectors
    F = ParamsInit.init_vec(robo)
    N = ParamsInit.init_vec(robo)
    Fjnt = ParamsInit.init_vec(robo)
    Njnt = ParamsInit.init_vec(robo)
    # init torque list
    torque = ParamsInit.init_scalar(robo)
    for j in xrange(0, robo.NL):
        compute_dynamic_wrench(robo, symo, j, w, wdot, U, vdot, F, N)
    for j in reversed(xrange(0, robo.NL)):
        compute_joint_wrench(
            robo, symo, j, antRj, antPj, vdot,
            F, N, Fjnt, Njnt, Fex, Nex
        )
    for j in xrange(1, robo.NL):
        compute_joint_torque(robo, symo, j, Fjnt, Njnt, torque)


def composite_inverse_dynmodel(robo, symo):
    """
    Compute the Inverse Dynamic Model using Composite link Newton-Euler
    algorithm for tree structure robots with fixed and floating base.

    Parameters:
        robo: Robot - instance of robot description container
        symo: symbolmgr.SymbolManager - instance of symbol manager
    """
    # antecedent angular velocity, projected into jth frame
    # j^omega_i
    wi = ParamsInit.init_vec(robo)
    # j^omega_j
    w = ParamsInit.init_w(robo)
    # j^a_j -- joint axis in screw form
    jaj = ParamsInit.init_vec(robo, 6)
    # Twist transform list of Matrices 6x6
    grandJ = ParamsInit.init_mat(robo, 6)
    jTant = ParamsInit.init_mat(robo, 6)
    gamma = ParamsInit.init_vec(robo, 6)
    beta = ParamsInit.init_vec(robo, 6)
    zeta = ParamsInit.init_vec(robo, 6)
    composite_inertia = ParamsInit.init_mat(robo, 6)
    composite_beta = ParamsInit.init_vec(robo, 6)
    comp_inertia3, comp_ms, comp_mass = ParamsInit.init_jplus(robo)
    grandVp = ParamsInit.init_vec(robo, 6)
    react_wrench = ParamsInit.init_vec(robo, 6)
    torque = ParamsInit.init_scalar(robo)
    # init transformation
    antRj, antPj = compute_rot_trans(robo, symo)
    # first forward recursion
    for j in xrange(1, robo.NL):
        # compute spatial inertia matrix for use in backward recursion
        grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
        # set jaj vector
        if robo.sigma[j] == 0:
            jaj[j] = Matrix([0, 0, 0, 0, 0, 1])
        elif robo.sigma[j] == 1:
            jaj[j] = Matrix([0, 0, 1, 0, 0, 0])
        # compute j^omega_j and j^omega_i
        compute_omega(robo, symo, j, antRj, w, wi)
        # compute j^S_i : screw transformation matrix
        compute_screw_transform(robo, symo, j, antRj, antPj, jTant)
    # first forward recursion (still)
    for j in xrange(1, robo.NL):
        # compute j^gamma_j : gyroscopic acceleration (6x1)
        compute_gamma(robo, symo, j, antRj, antPj, w, wi, gamma)
        # compute j^beta_j : external+coriolis+centrifugal wrench (6x1)
        compute_beta(robo, symo, j, w, beta)
        # compute j^zeta_j : relative acceleration (6x1)
        compute_zeta(robo, symo, j, gamma, jaj, zeta)
    # first backward recursion - initialisation step
    for j in reversed(xrange(0, robo.NL)):
        if j == 0:
            # compute spatial inertia matrix for base
            grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
            # compute 0^beta_0
            compute_beta(robo, symo, j, w, beta)
        replace_composite_terms(
            symo, grandJ, beta, j, composite_inertia, composite_beta
        )
    # second backward recursion - compute composite term
    for j in reversed(xrange(0, robo.NL)):
        if j == 0: continue
        compute_composite_inertia(
            robo, symo, j, antRj, antPj,
            comp_inertia3, comp_ms, comp_mass, composite_inertia
        )
        compute_composite_beta(
            robo, symo, j, jTant, zeta, composite_inertia, composite_beta
        )
        replace_composite_terms(
            symo, composite_inertia, composite_beta, robo.ant[j],
            composite_inertia, composite_beta, replace=True
        )
    # compute base acceleration : this returns the correct value for
    # fixed base and floating base robots
    compute_base_accel_composite(
        robo, symo, composite_inertia, composite_beta, grandVp
    )
    # second forward recursion
    for j in xrange(1, robo.NL):
        # compute j^Vdot_j : link acceleration
        compute_link_accel(robo, symo, j, jTant, zeta, grandVp)
        # compute j^F_j : reaction wrench
        compute_reaction_wrench(
            robo, symo, j, grandVp,
            composite_inertia, composite_beta, react_wrench
        )
        # compute torque
        compute_torque(robo, symo, j, jaj, react_wrench, torque)


def flexible_inverse_dynmodel(robo, symo):
    """
    Compute the Inverse Dynamic Model using Newton-Euler algorithm for
    robots with flexible joints (fixed and floating base).

    Parameters:
        robo: Robot - instance of robot description container
        symo: symbolmgr.SymbolManager - instance of symbol manager
    """
    # antecedent angular velocity, projected into jth frame
    # j^omega_i
    wi = ParamsInit.init_vec(robo)
    # j^omega_j
    w = ParamsInit.init_w(robo)
    # j^a_j -- joint axis in screw form
    jaj = ParamsInit.init_vec(robo, 6)
    # Twist transform list of Matrices 6x6
    grandJ = ParamsInit.init_mat(robo, 6)
    jTant = ParamsInit.init_mat(robo, 6)
    gamma = ParamsInit.init_vec(robo, 6)
    beta = ParamsInit.init_vec(robo, 6)
    zeta = ParamsInit.init_vec(robo, 6)
    h_inv = ParamsInit.init_scalar(robo)
    jah = ParamsInit.init_vec(robo, 6)   # Jj*aj*Hinv_j
    tau = ParamsInit.init_scalar(robo)
    star_inertia = ParamsInit.init_mat(robo, 6)
    star_beta = ParamsInit.init_vec(robo, 6)
    comp_inertia3, comp_ms, comp_mass = ParamsInit.init_jplus(robo)
    qddot = ParamsInit.init_scalar(robo)
    grandVp = ParamsInit.init_vec(robo, 6)
    react_wrench = ParamsInit.init_vec(robo, 6)
    torque = ParamsInit.init_scalar(robo)
    # flag variables
    use_composite = True
    # init transformation
    antRj, antPj = compute_rot_trans(robo, symo)
    # first forward recursion
    for j in xrange(1, robo.NL):
        # compute spatial inertia matrix for use in backward recursion
        grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
        # set jaj vector
        if robo.sigma[j] == 0:
            jaj[j] = Matrix([0, 0, 0, 0, 0, 1])
        elif robo.sigma[j] == 1:
            jaj[j] = Matrix([0, 0, 1, 0, 0, 0])
        # compute j^omega_j and j^omega_i
        compute_omega(robo, symo, j, antRj, w, wi)
        # compute j^S_i : screw transformation matrix
        compute_screw_transform(robo, symo, j, antRj, antPj, jTant)
        # compute j^gamma_j : gyroscopic acceleration (6x1)
        compute_gamma(robo, symo, j, antRj, antPj, w, wi, gamma)
        # compute j^beta_j : external+coriolis+centrifugal wrench (6x1)
        compute_beta(robo, symo, j, w, beta)
        if not robo.eta[j]:
            # when rigid
            # compute j^zeta_j : relative acceleration (6x1)
            compute_zeta(robo, symo, j, gamma, jaj, zeta)
    # first backward recursion - initialisation step
    for j in reversed(xrange(0, robo.NL)):
        if j == 0:
            # compute spatial inertia matrix for base
            grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
            # compute 0^beta_0
            compute_beta(robo, symo, j, w, beta)
        replace_star_terms(
            symo, grandJ, beta, j, star_inertia, star_beta
        )
    # second backward recursion - compute star terms
    for j in reversed(xrange(0, robo.NL)):
        if j == 0: continue
        # set composite flag to false when flexible
        if robo.eta[j]: use_composite = False
        if use_composite:
            # use composite
            compute_composite_inertia(
                robo, symo, j, antRj, antPj,
                comp_inertia3, comp_ms, comp_mass, star_inertia
            )
            compute_composite_beta(
                robo, symo, j, jTant, zeta, star_inertia, star_beta
            )
        else:
            # use star
            if robo.eta[j]:
                compute_tau(
                    robo, symo, j, jaj, star_beta, tau, flex=True
                )
            compute_star_terms(
                robo, symo, j, jaj, jTant, gamma, tau,
                h_inv, jah, star_inertia, star_beta, flex=True
            )
        replace_star_terms(
            symo, star_inertia, star_beta, robo.ant[j],
            star_inertia, star_beta
        )
    # compute base acceleration : this returns the correct value for
    # fixed base and floating base robots
    compute_base_accel(
        robo, symo, star_inertia, star_beta, grandVp
    )
    # second forward recursion
    for j in xrange(1, robo.NL):
        if robo.eta[j]:
            # when flexible
            # compute qddot_j : joint acceleration
            compute_joint_accel(
                robo, symo, j, jaj, jTant, h_inv, jah, gamma,
                tau, grandVp, star_beta, star_inertia, qddot
            )
            # compute j^zeta_j : relative acceleration (6x1)
            compute_zeta(robo, symo, j, gamma, jaj, zeta, qddot)
        # compute j^Vdot_j : link acceleration
        compute_link_accel(robo, symo, j, jTant, zeta, grandVp)
        # compute j^F_j : reaction wrench
        compute_reaction_wrench(
            robo, symo, j, grandVp,
            star_inertia, star_beta, react_wrench
        )
        if not robo.eta[j]:
            # when rigid compute torque
            compute_torque(robo, symo, j, jaj, react_wrench, torque)


def floating_direct_dynmodel(robo, symo):
    """
    Compute the Direct Dynamic Model using Newton-Euler algorithm for
    robots with floating base.

    Parameters:
        robo: Robot - instance of robot description container
        symo: symbolmgr.SymbolManager - instance of symbol manager
    """
    # antecedent angular velocity, projected into jth frame
    # j^omega_i
    wi = ParamsInit.init_vec(robo)
    # j^omega_j
    w = ParamsInit.init_w(robo)
    # j^a_j -- joint axis in screw form
    jaj = ParamsInit.init_vec(robo, 6)
    # Twist transform list of Matrices 6x6
    grandJ = ParamsInit.init_mat(robo, 6)
    jTant = ParamsInit.init_mat(robo, 6)
    gamma = ParamsInit.init_vec(robo, 6)
    beta = ParamsInit.init_vec(robo, 6)
    zeta = ParamsInit.init_vec(robo, 6)
    h_inv = ParamsInit.init_scalar(robo)
    jah = ParamsInit.init_vec(robo, 6)   # Jj*aj*Hinv_j
    tau = ParamsInit.init_scalar(robo)
    star_inertia = ParamsInit.init_mat(robo, 6)
    star_beta = ParamsInit.init_vec(robo, 6)
    qddot = ParamsInit.init_scalar(robo)
    grandVp = ParamsInit.init_vec(robo, 6)
    react_wrench = ParamsInit.init_vec(robo, 6)
    torque = ParamsInit.init_scalar(robo)
    # init transformation
    antRj, antPj = compute_rot_trans(robo, symo)
    # first forward recursion
    for j in xrange(1, robo.NL):
        # compute spatial inertia matrix for use in backward recursion
        grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
        # set jaj vector
        if robo.sigma[j] == 0:
            jaj[j] = Matrix([0, 0, 0, 0, 0, 1])
        elif robo.sigma[j] == 1:
            jaj[j] = Matrix([0, 0, 1, 0, 0, 0])
        # compute j^omega_j and j^omega_i
        compute_omega(robo, symo, j, antRj, w, wi)
        # compute j^S_i : screw transformation matrix
        compute_screw_transform(robo, symo, j, antRj, antPj, jTant)
        # compute j^gamma_j : gyroscopic acceleration (6x1)
        compute_gamma(robo, symo, j, antRj, antPj, w, wi, gamma)
        # compute j^beta_j : external+coriolis+centrifugal wrench (6x1)
        compute_beta(robo, symo, j, w, beta)
    # first backward recursion - initialisation step
    for j in reversed(xrange(0, robo.NL)):
        if j == 0:
            # compute spatial inertia matrix for base
            grandJ[j] = inertia_spatial(robo.J[j], robo.MS[j], robo.M[j])
            # compute 0^beta_0
            compute_beta(robo, symo, j, w, beta)
        replace_star_terms(
            symo, grandJ, beta, j, star_inertia, star_beta
        )
    # second backward recursion - compute star terms
    for j in reversed(xrange(0, robo.NL)):
        if j == 0: continue
        compute_tau(robo, symo, j, jaj, star_beta, tau)
        compute_star_terms(
            robo, symo, j, jaj, jTant, gamma, tau,
            h_inv, jah, star_inertia, star_beta
        )
        replace_star_terms(
            symo, star_inertia, star_beta, robo.ant[j],
            star_inertia, star_beta, replace=True
        )
    # compute base acceleration : this returns the correct value for
    # fixed base and floating base robots
    compute_base_accel(
        robo, symo, star_inertia, star_beta, grandVp
    )
    # second forward recursion
    for j in xrange(1, robo.NL):
        # compute qddot_j : joint acceleration
        compute_joint_accel(
            robo, symo, j, jaj, jTant, h_inv, jah, gamma,
            tau, grandVp, star_beta, star_inertia, qddot
        )
        # compute j^zeta_j : relative acceleration (6x1)
        compute_zeta(robo, symo, j, gamma, jaj, zeta, qddot)
        # compute j^Vdot_j : link acceleration
        compute_link_accel(robo, symo, j, jTant, zeta, grandVp)
        # compute j^F_j : reaction wrench
        compute_reaction_wrench(
            robo, symo, j, grandVp,
            star_inertia, star_beta, react_wrench
        )



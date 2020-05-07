import copy
import gmpy
import numpy as np

def normalize(M):
    M = M.astype(float)
    if M.ndim > 1:
        denoms = M.sum(axis=1)[:,None]
    else:
        denoms = M.sum()
    M = np.divide(M, denoms.astype(float), out=np.zeros_like(M), where=(denoms!=0))
    return M

def is_stochastic(M):
    return np.allclose(M, normalize(M))

def random_sparse_mask(size, sparsity):
    n_rows, n_cols = size
    p = (1-sparsity)# probability of 1
    q = (n_cols*p - 1)/(n_cols-1)# get remaining probability after mandatory 1s
    if 0 < q <= 1:
        some_ones = np.random.choice([0,1],size=(n_rows, n_cols-1),p=[1-q, q])
        mask = np.concatenate([np.ones((n_rows,1)), some_ones], axis=1)
    else:
        mask = np.concatenate([np.ones((n_rows,1)), np.zeros((n_rows, n_cols-1))], axis=1)
    for row in mask:
        np.random.shuffle(row)
    return mask

def random_transition_matrix(size):
    T = normalize(np.random.rand(*size))
    return T

def random_reward_matrix(Rmin, Rmax, size):
    R = np.random.uniform(Rmin, Rmax, size)
    R = np.round(R, 2)
    return R

def random_observation_fn(n_states, n_obs_per_block):
    all_state_splits = [random_transition_matrix(size=(1,n_obs_per_block))
                        for _ in range(n_states)]
    all_state_splits = np.stack(all_state_splits).squeeze()
    #e.g.[[p, 1-p],
    #     [q, 1-q],
    #     ...]

    obs_fn_mask = np.kron(np.eye(n_states), np.ones((1,n_obs_per_block)))
    #e.g.[[1, 1, 0, 0, 0, 0, ...],
    #     [0, 0, 1, 1, 0, 0, ...],
    #     ...]

    tiled_split_probs = np.kron(np.ones((1,n_states)), all_state_splits)
    #e.g.[[p, 1-p, p, 1-p, p, 1-p, ...],
    #     [q, 1-q, q, 1-q, q, 1-q, ...],
    #     ...]

    observation_fn = obs_fn_mask*tiled_split_probs
    return observation_fn

def one_hot(x, n):
    return np.eye(n)[x]

class MDP:
    def __init__(self, T, R, gamma=0.9):
        self.n_states = len(T[0])
        self.n_actions = len(T)
        self.gamma = gamma
        self.T = copy.deepcopy(T)
        self.R = copy.deepcopy(R)
        self.R_min = np.min(np.stack(self.R))
        self.R_max = np.max(np.stack(self.R))
        if not isinstance(self.T, np.ndarray):
            self.T = np.stack(self.T)
        if not isinstance(self.R, np.ndarray):
            self.R = np.stack(self.R)

    def get_policy(self, i):
        assert i < self.n_actions**self.n_states
        pi_string = gmpy.digits(i, self.n_actions).zfill(self.n_states)
        pi = np.asarray(list(pi_string), dtype=int)
        return pi

    def all_policies(self):
        policies = []
        n_policies = self.n_actions**self.n_states
        for i in range(n_policies):
            pi = self.get_policy(i)
            policies.append(pi)
        return policies

    def stationary_distribution(self, pi=None, p0=None, max_steps=200):
        if p0 is None:
            state_distr = np.ones(self.n_states)/self.n_states
        else:
            state_distr = p0
        old_distr = state_distr
        for t in range(max_steps):
            state_distr = self.image(state_distr, pi)
            if np.allclose(state_distr, old_distr):
                break
            old_distr = state_distr
        return state_distr

    def image(self, pr_x, pi=None):
        if pi is None:
            # Assume uniform random policy
            T = np.mean(self.T, axis=0)
            # R = self.R * T[None,:,:]
        else:
            pi_t = pi
            T = self.T_pi(pi_t)
            # R = self.R * T[None,:,:]
        pr_next_x = pr_x @ T
        return pr_next_x

    def T_pi(self, pi):
        return self.T[pi, np.arange(self.n_states),:]

    def get_N(self, pi):
        return self.T_pi(pi)

    def get_I(self, pi):
        pi_one_hot = one_hot(pi,self.n_actions).transpose()[:,:,None]
        N = self.get_N(pi)[None,:,:]
        I = np.divide(self.T*pi_one_hot, N, out=np.zeros_like(self.T), where=N!=0)
        return I

    @classmethod
    def generate(cls, n_states, n_actions, sparsity=0, gamma=0.9, Rmin=-1, Rmax=1):
        T = []# List of s -> s transition matrices, one for each action
        R = []# List of s -> s reward matrices, one for each action
        for a in range(n_actions):
            T_a = random_transition_matrix(size=(n_states, n_states))
            R_a = random_reward_matrix(Rmin, Rmax, (n_states, n_states))
            if sparsity > 0:
                mask = random_sparse_mask((n_states, n_states), sparsity)
                T_a = normalize(T_a*mask)
                R_a = R_a*mask
            T.append(T_a)
            R.append(R_a)
        mdp = cls(T, R, gamma)
        return mdp

class BlockMDP(MDP):
    def __init__(self, base_mdp, n_obs_per_block=2, obs_fn=None):
        super().__init__(base_mdp.T, base_mdp.R, base_mdp.gamma)
        self.base_mdp = copy.deepcopy(base_mdp)
        self.n_states = base_mdp.n_states*n_obs_per_block

        if obs_fn is None:
            obs_fn = random_observation_fn(base_mdp.n_states, n_obs_per_block)
        else:
            n_obs_per_block = obs_fn.shape[1]

        obs_mask = (obs_fn > 0).astype(int)

        self.T = []# List of x -> x transition matrices, one for each action
        self.R = []# List of x -> x reward matrices, one for each action
        for a in range(self.n_actions):
            Ta, Ra = base_mdp.T[a], base_mdp.R[a]
            Tx_a = obs_mask.transpose() @ Ta @ obs_fn
            Rx_a = obs_mask.transpose() @ Ra @ obs_mask
            self.T.append(Tx_a)
            self.R.append(Rx_a)
        self.T = np.stack(self.T)
        self.R = np.stack(self.R)
        self.obs_fn = obs_fn

class AbstractMDP(MDP):
    def __init__(self, base_mdp, phi, pi=None, p0=None):
        super().__init__(base_mdp.T, base_mdp.R, base_mdp.gamma)
        self.base_mdp = copy.deepcopy(base_mdp)
        self.phi = phi# array: base_mdp.n_states, n_abstract_states
        self.n_states = phi.shape[-1]
        self.n_obs = base_mdp.n_states

        state_distr = self.base_mdp.stationary_distribution(pi=pi, p0=p0)
        self.belief = self.B(state_distr)
        self.T = [self.compute_Tz(self.belief,T_a)
                    for T_a in base_mdp.T]
        self.R = [self.compute_Rz(self.belief,Rx_a,Tx_a,Tz_a)
                    for (Rx_a, Tx_a, Tz_a) in zip(base_mdp.R, base_mdp.T, self.T)]
        self.T = np.stack(self.T)
        self.R = np.stack(self.R)
        self.Rmin = np.min(np.stack(self.R))
        self.Rmax = np.max(np.stack(self.R))

    def B(self, p):
        return normalize(p*self.phi.transpose())

    def compute_Tz(self, belief, Tx):
        return belief @ Tx @ self.phi

    def compute_Rz(self, belief, Rx, Tx, Tz):
        return np.divide( (belief@(Rx*Tx)@self.phi), Tz,
                         out=np.zeros_like(Tz), where=(Tz!=0) )

    def is_abstract_policy(self, pi):
        agg_states = ((self.phi.sum(axis=0)>1) @ self.phi.transpose()).astype(bool)
        return np.all(pi[agg_states] == pi[agg_states][0])

    def piecewise_constant_policies(self):
        return [pi for pi in self.base_mdp.all_policies() if self.is_abstract_policy(pi)]

    def get_abstract_policy(self, pi):
        assert self.is_abstract_policy(pi)
        mask = self.phi.transpose()
        obs_fn = normalize(mask)
        return (pi @ obs_fn.transpose()).astype(int)

    def abstract_policies(self):
        pi_list = self.piecewise_constant_policies()
        return [self.get_abstract_policy(pi) for pi in pi_list]

    def is_markov(self):
        m_a = self
        m_g = m_a.base_mdp
        phi = m_a.phi
        for pi_g in self.piecewise_constant_policies(m_g, phi):
            pi_a = self.get_abstract_policy(pi_g, phi)
            if not markov.matching_I(m_g, m_a, pi_g, pi_a):
                return False
            if not markov.matching_ratios(m_g, m_a, pi_g, pi_a):
                return False
        return True


def test():
    # Generate a random base MDP
    mdp1 = MDP.generate(n_states=5, n_actions=3, sparsity=0.5)
    assert all([is_stochastic(mdp1.T[a]) for a in range(mdp1.n_actions)])

    # Add block structure to the base MDP
    mdp2 = BlockMDP(mdp1, n_obs_per_block=2)
    assert all([np.allclose(mdp2.base_mdp.T[a],mdp1.T[a]) for a in range(mdp1.n_actions)])
    assert all([np.allclose(mdp2.base_mdp.R[a],mdp1.R[a]) for a in range(mdp1.n_actions)])

    # Construct abstract MDP of the block MDP using perfect abstraction function
    phi = (mdp2.obs_fn.transpose()>0).astype(int)
    mdp3 = AbstractMDP(mdp2, phi)
    assert np.allclose(mdp1.T, mdp3.T)
    assert np.allclose(mdp1.R, mdp3.R)
    print('All tests passed.')

if __name__ == '__main__':
    test()

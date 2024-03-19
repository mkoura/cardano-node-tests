"""Tests for Conway governance protocol parameters update."""

# pylint: disable=expression-not-assigned
import fractions
import logging
import pathlib as pl
import random
import typing as tp

import allure
import pytest
from cardano_clusterlib import clusterlib

from cardano_node_tests.cluster_management import cluster_management
from cardano_node_tests.tests import common
from cardano_node_tests.tests.tests_conway import conway_common
from cardano_node_tests.utils import clusterlib_utils
from cardano_node_tests.utils import configuration
from cardano_node_tests.utils import governance_setup
from cardano_node_tests.utils import governance_utils
from cardano_node_tests.utils import helpers
from cardano_node_tests.utils import requirements
from cardano_node_tests.utils.versions import VERSIONS

LOGGER = logging.getLogger(__name__)
DATA_DIR = pl.Path(__file__).parent.parent / "data"

pytestmark = pytest.mark.skipif(
    VERSIONS.transaction_era < VERSIONS.CONWAY,
    reason="runs only with Tx era >= Conway",
)


NETWORK_GROUP_PPARAMS = {
    "maxBlockBodySize",
    "maxTxSize",
    "maxBlockHeaderSize",
    "maxValSize",
    "maxTxExUnits",
    "maxBlockExUnits",
    "maxCollateralInputs",
}

ECONOMIC_GROUP_PPARAMS = {
    "minFeeA",
    "minFeeB",
    "keyDeposit",
    "poolDeposit",
    "rho",
    "tau",
    "minPoolCost",
    "coinsPerUTxOByte",
    "prices",
}

TECHNICAL_GROUP_PPARAMS = {
    "a0",
    "eMax",
    "nOpt",
    "costmdls",
    "collateralPercentage",
}

GOVERNANCE_GROUP_PPARAMS = {
    "govActionLifetime",
    "govActionDeposit",
    "dRepDeposit",
    "dRepActivity",
    "committeeMinSize",
    "committeeMaxTermLength",
}

GOVERNANCE_GROUP_PPARAMS_DREP_THRESHOLDS = {
    "committeeNoConfidence",
    "committeeNormal",
    "hardForkInitiation",
    "motionNoConfidence",
    "ppEconomicGroup",
    "ppGovGroup",
    "ppNetworkGroup",
    "ppTechnicalGroup",
    "treasuryWithdrawal",
    "updateToConstitution",
}

GOVERNANCE_GROUP_PPARAMS_POOL_THRESHOLDS = {
    "committeeNoConfidence",
    "committeeNormal",
    "hardForkInitiation",
    "motionNoConfidence",
    "ppSecurityGroup",
}

# Security related pparams that require also SPO approval
SECURITY_PPARAMS = {
    "maxBlockBodySize",
    "maxTxSize",
    "maxBlockHeaderSize",
    "maxValSize",
    "maxBlockExUnits",
    "minFeeA",
    "minFeeB",
    "coinsPerUTxOByte",
    "govActionDeposit",
    "minFeeRefScriptsCoinsPerByte",  # not in 8.8 release yet
}


@pytest.fixture
def pool_user_lg(
    cluster_manager: cluster_management.ClusterManager,
    cluster_lock_governance: governance_setup.GovClusterT,
) -> clusterlib.PoolUser:
    """Create a pool user for "lock governance"."""
    cluster, __ = cluster_lock_governance
    key = helpers.get_current_line_str()
    return conway_common.get_pool_user(
        cluster_manager=cluster_manager,
        cluster_obj=cluster,
        caching_key=key,
        fund_amount=2000_000_000,
    )


def _get_rational_str(value: float) -> str:
    return str(fractions.Fraction(value).limit_denominator())


class TestPParamUpdate:
    """Tests for protocol parameters update."""

    @allure.link(helpers.get_vcs_link())
    @pytest.mark.long
    def test_pparam_update(  # noqa: C901
        self,
        cluster_lock_governance: governance_setup.GovClusterT,
        pool_user_lg: clusterlib.PoolUser,
    ):
        """Test enactment of protocol parameter update.

        * submit multiple "protocol parameters update" action

            - one action for each parameter group
            - one action with multiple proposals from different groups

        * vote to disapprove the actions
        * submit a "protocol parameters update" action that will be enacted
        * check that SPOs cannot vote on a "protocol parameters update" action
        * vote to approve the action
        * check that the action is ratified
        * try to disapprove the ratified action, this shouldn't have any effect
        * check that the action is enacted
        * check that it's not possible to vote on enacted action
        """
        # pylint: disable=too-many-locals,too-many-statements
        cluster, governance_data = cluster_lock_governance
        temp_template = common.get_test_id(cluster)
        cost_proposal_file = DATA_DIR / "cost_models_list.json"
        deposit_amt = cluster.conway_genesis["govActionDeposit"]

        # Linked user stories
        req_cli17 = requirements.Req(id="CLI017", group=requirements.GroupsKnown.CHANG_US)
        req_cip6 = requirements.Req(id="CIP006", group=requirements.GroupsKnown.CHANG_US)
        req_cip31a = requirements.Req(id="intCIP031a-05", group=requirements.GroupsKnown.CHANG_US)
        req_cip31e = requirements.Req(id="CIP031e", group=requirements.GroupsKnown.CHANG_US)
        req_cip37 = requirements.Req(id="CIP037", group=requirements.GroupsKnown.CHANG_US)
        req_cip44 = requirements.Req(id="CIP044", group=requirements.GroupsKnown.CHANG_US)
        req_cip45 = requirements.Req(id="CIP045", group=requirements.GroupsKnown.CHANG_US)
        req_cip46 = requirements.Req(id="CIP046", group=requirements.GroupsKnown.CHANG_US)
        req_cip47 = requirements.Req(id="CIP047", group=requirements.GroupsKnown.CHANG_US)
        req_cip49 = requirements.Req(id="CIP049", group=requirements.GroupsKnown.CHANG_US)
        req_cip50 = requirements.Req(id="CIP050", group=requirements.GroupsKnown.CHANG_US)
        req_cip51 = requirements.Req(id="CIP051", group=requirements.GroupsKnown.CHANG_US)
        req_cip52 = requirements.Req(id="CIP052", group=requirements.GroupsKnown.CHANG_US)
        req_cip54_01 = requirements.Req(id="intCIP054-01", group=requirements.GroupsKnown.CHANG_US)
        req_cip60 = requirements.Req(id="CIP060", group=requirements.GroupsKnown.CHANG_US)
        req_cip64_03 = requirements.Req(id="intCIP064-03", group=requirements.GroupsKnown.CHANG_US)
        req_cip64_04 = requirements.Req(id="intCIP064-04", group=requirements.GroupsKnown.CHANG_US)
        req_cip65 = requirements.Req(id="CIP065", group=requirements.GroupsKnown.CHANG_US)
        req_cip68 = requirements.Req(id="CIP068", group=requirements.GroupsKnown.CHANG_US)
        req_cip74 = requirements.Req(id="CIP074", group=requirements.GroupsKnown.CHANG_US)

        # Check if total delegated stake is below the threshold. This can be used to check that
        # undelegated stake is treated as Abstain. If undelegated stake was treated as Yes, than
        # missing votes would approve the action.
        delegated_stake = governance_utils.get_delegated_stake(cluster_obj=cluster)
        cur_pparams = cluster.g_conway_governance.query.gov_state()["enactState"]["curPParams"]
        drep_constitution_threshold = cur_pparams["dRepVotingThresholds"]["ppGovGroup"]
        spo_constitution_threshold = cur_pparams["poolVotingThresholds"]["ppSecurityGroup"]
        is_drep_total_below_threshold = (
            delegated_stake.drep / delegated_stake.total_lovelace
        ) < drep_constitution_threshold
        is_spo_total_below_threshold = (
            delegated_stake.spo / delegated_stake.total_lovelace
        ) < spo_constitution_threshold

        # PParam groups

        _groups_url = helpers.get_vcs_link()
        [r.start(url=_groups_url) for r in (req_cip49, req_cip50, req_cip51, req_cip52)]

        network_g_proposals = [
            clusterlib_utils.UpdateProposal(
                arg="--max-block-body-size",
                value=65544,
                name="maxBlockBodySize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-tx-size",
                value=16392,
                name="maxTxSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-block-header-size",
                value=random.randint(1101, 1200),
                name="maxBlockHeaderSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-value-size",
                value=random.randint(5001, 5100),
                name="maxValSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-tx-execution-units",
                value=f"({random.randint(14000001, 14000100)},"
                f"{random.randint(10000000001, 10000000100)})",
                name="",  # needs custom check of `maxTxExUnits`
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-block-execution-units",
                value=f"({random.randint(62000001, 62000100)},"
                f"{random.randint(40000000001, 40000000100)})",
                name="",  # needs custom check of `maxBlockExUnits`
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-collateral-inputs",
                value=random.randint(3, 10),
                name="maxCollateralInputs",
            ),
        ]

        economic_g_proposals = [
            clusterlib_utils.UpdateProposal(
                arg="--min-fee-linear",
                value=44,
                name="minFeeA",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--min-fee-constant",
                value=155381,
                name="minFeeB",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--key-reg-deposit-amt",
                value=random.randint(400001, 400100),
                name="keyDeposit",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--pool-reg-deposit",
                value=random.randint(500000001, 500000100),
                name="poolDeposit",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--monetary-expansion",
                value=_get_rational_str(random.uniform(0.0023, 0.0122)),
                name="rho",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--treasury-expansion",
                value=_get_rational_str(random.uniform(0.051, 0.1)),
                name="tau",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--min-pool-cost",
                value=random.randint(0, 10),
                name="minPoolCost",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--utxo-cost-per-byte",
                value=random.randint(4311, 4400),
                name="coinsPerUTxOByte",
            ),
            # These must be passed together
            [
                clusterlib_utils.UpdateProposal(
                    arg="--price-execution-steps",
                    value=_get_rational_str(random.uniform(0.0578, 0.0677)),
                    name="",  # prices
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--price-execution-memory",
                    value=_get_rational_str(random.uniform(0.00008, 0.00009)),
                    name="",  # prices
                ),
            ],
        ]

        technical_g_proposals = [
            clusterlib_utils.UpdateProposal(
                arg="--pool-influence",
                value=_get_rational_str(random.uniform(0.1, 0.5)),
                name="a0",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--pool-retirement-epoch-interval",
                value=random.randint(19, 30),
                name="eMax",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--number-of-pools",
                value=random.randint(500, 400100),
                name="nOpt",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--cost-model-file",
                value=str(cost_proposal_file),
                name="costmdls",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--collateral-percent",
                value=random.randint(151, 160),
                name="collateralPercentage",
            ),
        ]

        governance_g_proposals = [
            # These must be passed together
            [
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-committee-no-confidence",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `committeeNoConfidence`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-committee-normal",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `committeeNormal`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-hard-fork-initiation",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `hardForkInitiation`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-motion-no-confidence",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `motionNoConfidence`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-pp-economic-group",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="ppEconomicGroup",
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-pp-governance-group",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="ppGovGroup",
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-pp-network-group",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="ppNetworkGroup",
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-pp-technical-group",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="ppTechnicalGroup",
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-treasury-withdrawal",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="treasuryWithdrawal",
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--drep-voting-threshold-update-to-constitution",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="updateToConstitution",
                ),
            ],
            # These must be passed together
            [
                clusterlib_utils.UpdateProposal(
                    arg="--pool-voting-threshold-committee-no-confidence",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `committeeNoConfidence`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--pool-voting-threshold-committee-normal",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `committeeNormal`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--pool-voting-threshold-hard-fork-initiation",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `hardForkInitiation`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--pool-voting-threshold-motion-no-confidence",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="",  # needs custom check of `motionNoConfidence`
                ),
                clusterlib_utils.UpdateProposal(
                    arg="--pool-voting-threshold-pp-security-group",
                    value=_get_rational_str(random.uniform(0.52, 0.60)),
                    name="ppSecurityGroup",
                ),
            ],
            clusterlib_utils.UpdateProposal(
                arg="--governance-action-lifetime",
                value=random.randint(3, 10),
                name="govActionLifetime",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--new-governance-action-deposit",
                value=random.randint(100000001, 100000100),
                name="govActionDeposit",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--drep-deposit",
                value=random.randint(2000001, 2000100),
                name="dRepDeposit",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--drep-activity",
                value=random.randint(101, 200),
                name="dRepActivity",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--min-committee-size",
                value=1,
                name="committeeMinSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--committee-term-length",
                value=random.randint(11001, 12000),
                name="committeeMaxTermLength",
            ),
        ]

        security_proposals = [
            clusterlib_utils.UpdateProposal(
                arg="--max-block-body-size",
                value=65544,
                name="maxBlockBodySize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-tx-size",
                value=16392,
                name="maxTxSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-block-header-size",
                value=random.randint(1101, 1200),
                name="maxBlockHeaderSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-value-size",
                value=random.randint(5001, 5100),
                name="maxValSize",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--max-block-execution-units",
                value=f"({random.randint(62000001, 62000100)},"
                f"{random.randint(40000000001, 40000000100)})",
                name="",  # needs custom check of `maxBlockExUnits`
            ),
            clusterlib_utils.UpdateProposal(
                arg="--min-fee-linear",
                value=44,
                name="minFeeA",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--min-fee-constant",
                value=155381,
                name="minFeeB",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--utxo-cost-per-byte",
                value=random.randint(4311, 4400),
                name="coinsPerUTxOByte",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--new-governance-action-deposit",
                value=random.randint(100000001, 100000100),
                name="govActionDeposit",
            ),
        ]

        # Hand-picked parameters and values that can stay changed even for other tests
        cur_pparams = cluster.g_conway_governance.query.gov_state()["enactState"]["curPParams"]
        fin_update_proposals = [
            # From network group
            clusterlib_utils.UpdateProposal(
                arg="--max-collateral-inputs",
                value=cur_pparams["maxCollateralInputs"],
                name="maxCollateralInputs",
            ),
            # From economic group
            clusterlib_utils.UpdateProposal(
                arg="--min-pool-cost",
                value=cur_pparams["minPoolCost"],
                name="minPoolCost",
            ),
            # From technical group
            clusterlib_utils.UpdateProposal(
                arg="--collateral-percent",
                value=cur_pparams["collateralPercentage"],
                name="collateralPercentage",
            ),
            # From governance group
            clusterlib_utils.UpdateProposal(
                arg="--committee-term-length",
                value=random.randint(11000, 12000),
                name="committeeMaxTermLength",
            ),
            clusterlib_utils.UpdateProposal(
                arg="--drep-activity",
                value=random.randint(101, 120),
                name="dRepActivity",
            ),
            # From security pparams
            clusterlib_utils.UpdateProposal(
                arg="--max-tx-size",
                value=cur_pparams["maxTxSize"],
                name="maxTxSize",
            ),
        ]
        if configuration.HAS_CC:
            fin_update_proposals.append(
                clusterlib_utils.UpdateProposal(
                    arg="--min-committee-size",
                    value=random.randint(3, 5),
                    name="committeeMinSize",
                )
            )

        # Intentionally use the same previous action for all proposals
        prev_action_rec = governance_utils.get_prev_action(
            action_type=governance_utils.PrevGovActionIds.PPARAM_UPDATE,
            gov_state=cluster.g_conway_governance.query.gov_state(),
        )

        _action_url = helpers.get_vcs_link()

        def _create_pparams_action(
            proposals: tp.List[clusterlib_utils.UpdateProposal],
        ) -> tp.Tuple[str, int, tp.Set[str]]:
            anchor_url = f"http://www.pparam-action-{clusterlib.get_rand_str(4)}.com"
            anchor_data_hash = cluster.g_conway_governance.get_anchor_data_hash(text=anchor_url)

            update_args = clusterlib_utils.get_pparams_update_args(update_proposals=proposals)

            [r.start(url=_action_url) for r in (req_cli17, req_cip31a, req_cip31e, req_cip54_01)]
            if configuration.HAS_CC:
                req_cip6.start(url=_action_url)
            pparams_action = cluster.g_conway_governance.action.create_pparams_update(
                action_name=temp_template,
                deposit_amt=deposit_amt,
                anchor_url=anchor_url,
                anchor_data_hash=anchor_data_hash,
                cli_args=update_args,
                prev_action_txid=prev_action_rec.txid,
                prev_action_ix=prev_action_rec.ix,
                deposit_return_stake_vkey_file=pool_user_lg.stake.vkey_file,
            )
            [r.success() for r in (req_cip31a, req_cip31e, req_cip54_01)]

            tx_files_action = clusterlib.TxFiles(
                proposal_files=[pparams_action.action_file],
                signing_key_files=[pool_user_lg.payment.skey_file],
            )

            # Make sure we have enough time to submit the proposal in one epoch
            clusterlib_utils.wait_for_epoch_interval(
                cluster_obj=cluster, start=1, stop=common.EPOCH_STOP_SEC_BUFFER
            )

            tx_output_action = clusterlib_utils.build_and_submit_tx(
                cluster_obj=cluster,
                name_template=f"{temp_template}_action",
                src_address=pool_user_lg.payment.address,
                use_build_cmd=True,
                tx_files=tx_files_action,
            )

            out_utxos_action = cluster.g_query.get_utxo(tx_raw_output=tx_output_action)
            assert (
                clusterlib.filter_utxos(
                    utxos=out_utxos_action, address=pool_user_lg.payment.address
                )[0].amount
                == clusterlib.calculate_utxos_balance(tx_output_action.txins)
                - tx_output_action.fee
                - deposit_amt
            ), f"Incorrect balance for source address `{pool_user_lg.payment.address}`"

            action_txid = cluster.g_transaction.get_txid(tx_body_file=tx_output_action.out_file)
            action_gov_state = cluster.g_conway_governance.query.gov_state()
            _cur_epoch = cluster.g_query.get_epoch()
            conway_common.save_gov_state(
                gov_state=action_gov_state, name_template=f"{temp_template}_action_{_cur_epoch}"
            )
            prop_action = governance_utils.lookup_proposal(
                gov_state=action_gov_state, action_txid=action_txid
            )
            assert prop_action, "Param update action not found"
            assert (
                prop_action["action"]["tag"] == governance_utils.ActionTags.PARAMETER_CHANGE.value
            ), "Incorrect action tag"
            req_cli17.success()

            action_ix = prop_action["actionId"]["govActionIx"]
            proposal_names = {p.name for p in proposals}

            return action_txid, action_ix, proposal_names

        _url = helpers.get_vcs_link()
        [r.start(url=_url) for r in (req_cip44, req_cip45, req_cip46, req_cip47, req_cip60)]

        # Vote on update proposals from network group that will NOT get approved by DReps
        net_nodrep_update_proposals = random.sample(network_g_proposals, 3)
        net_nodrep_action_txid, net_nodrep_action_ix, net_nodrep_proposal_names = (
            _create_pparams_action(proposals=net_nodrep_update_proposals)
        )
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_net_nodrep",
            payment_addr=pool_user_lg.payment,
            action_txid=net_nodrep_action_txid,
            action_ix=net_nodrep_action_ix,
            approve_cc=True,
            approve_drep=False,
            approve_spo=None if net_nodrep_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
        )

        # Vote on update proposals from network group that will NOT get approved by CC
        if configuration.HAS_CC:
            net_nocc_update_proposals = random.sample(network_g_proposals, 3)
            net_nocc_action_txid, net_nocc_action_ix, net_nocc_proposal_names = (
                _create_pparams_action(proposals=net_nocc_update_proposals)
            )
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_net_nocc",
                payment_addr=pool_user_lg.payment,
                action_txid=net_nocc_action_txid,
                action_ix=net_nocc_action_ix,
                approve_cc=False,
                approve_drep=True,
                approve_spo=None if net_nocc_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
            )

        # Vote on update proposals from economic group that will NOT get approved by DReps
        eco_nodrep_update_proposals = list(helpers.flatten(random.sample(economic_g_proposals, 3)))
        eco_nodrep_action_txid, eco_nodrep_action_ix, eco_nodrep_proposal_names = (
            _create_pparams_action(proposals=eco_nodrep_update_proposals)
        )
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_eco_nodrep",
            payment_addr=pool_user_lg.payment,
            action_txid=eco_nodrep_action_txid,
            action_ix=eco_nodrep_action_ix,
            approve_cc=True,
            approve_drep=False,
            approve_spo=None if eco_nodrep_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
        )

        # Vote on update proposals from economic group that will NOT get approved by CC
        if configuration.HAS_CC:
            eco_nocc_update_proposals = list(
                helpers.flatten(random.sample(economic_g_proposals, 3))
            )
            eco_nocc_action_txid, eco_nocc_action_ix, eco_nocc_proposal_names = (
                _create_pparams_action(proposals=eco_nocc_update_proposals)
            )
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_eco_nocc",
                payment_addr=pool_user_lg.payment,
                action_txid=eco_nocc_action_txid,
                action_ix=eco_nocc_action_ix,
                approve_cc=False,
                approve_drep=True,
                approve_spo=None if eco_nocc_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
            )

        # Vote on update proposals from technical group that will NOT get approved by DReps
        tech_nodrep_update_proposals = random.sample(technical_g_proposals, 3)
        tech_nodrep_action_txid, tech_nodrep_action_ix, tech_nodrep_proposal_names = (
            _create_pparams_action(proposals=tech_nodrep_update_proposals)
        )

        assert tech_nodrep_proposal_names.isdisjoint(
            SECURITY_PPARAMS
        ), "There are security pparams being changed"

        # Check that SPOs cannot vote on change of constitution action if no security params
        # are being changed.
        with pytest.raises(clusterlib.CLIError) as excinfo:
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_fin_with_spos",
                payment_addr=pool_user_lg.payment,
                action_txid=tech_nodrep_action_txid,
                action_ix=tech_nodrep_action_ix,
                approve_cc=False,
                approve_drep=False,
                approve_spo=True,
            )
        err_str = str(excinfo.value)
        assert "StakePoolVoter" in err_str, err_str

        _url = helpers.get_vcs_link()
        req_cip65.start(url=_url)
        if is_drep_total_below_threshold:
            req_cip64_03.start(url=_url)

        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_tech_nodrep",
            payment_addr=pool_user_lg.payment,
            action_txid=tech_nodrep_action_txid,
            action_ix=tech_nodrep_action_ix,
            approve_cc=True,
            approve_drep=None,
        )

        # Vote on update proposals from technical group that will NOT get approved by CC
        if configuration.HAS_CC:
            tech_nocc_update_proposals = random.sample(technical_g_proposals, 3)
            tech_nocc_action_txid, tech_nocc_action_ix, tech_nocc_proposal_names = (
                _create_pparams_action(proposals=tech_nocc_update_proposals)
            )
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_tech_nocc",
                payment_addr=pool_user_lg.payment,
                action_txid=tech_nocc_action_txid,
                action_ix=tech_nocc_action_ix,
                approve_cc=None,
                approve_drep=True,
                approve_spo=None if tech_nocc_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
            )

        # Vote on update proposals from security params that will NOT get approved by SPOs
        _url = helpers.get_vcs_link()
        req_cip74.start(url=_url)
        if is_spo_total_below_threshold:
            req_cip64_04.start(url=_url)
        sec_nospo_update_proposals = random.sample(security_proposals, 3)
        sec_nospo_action_txid, sec_nospo_action_ix, sec_nospo_proposal_names = (
            _create_pparams_action(proposals=sec_nospo_update_proposals)
        )
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_sec_nospo",
            payment_addr=pool_user_lg.payment,
            action_txid=sec_nospo_action_txid,
            action_ix=sec_nospo_action_ix,
            approve_cc=True,
            approve_drep=True,
            approve_spo=None,
        )

        # Vote on the final action that will be enacted
        req_cip37.start(url=_action_url)
        fin_action_txid, fin_action_ix, fin_proposal_names = _create_pparams_action(
            proposals=fin_update_proposals
        )

        # Vote & disapprove the action
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_fin_no",
            payment_addr=pool_user_lg.payment,
            action_txid=fin_action_txid,
            action_ix=fin_action_ix,
            approve_cc=False,
            approve_drep=False,
            approve_spo=False,
        )

        # Vote & approve the action
        fin_voted_votes = conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_fin_yes",
            payment_addr=pool_user_lg.payment,
            action_txid=fin_action_txid,
            action_ix=fin_action_ix,
            approve_cc=True,
            approve_drep=True,
            approve_spo=True,
        )
        fin_approve_epoch = cluster.g_query.get_epoch()

        # Vote on update proposals from governance group that will NOT get approved by DReps
        gov_nodrep_update_proposals = list(
            helpers.flatten(random.sample(governance_g_proposals, 3))
        )
        gov_nodrep_action_txid, gov_nodrep_action_ix, gov_nodrep_proposal_names = (
            _create_pparams_action(proposals=gov_nodrep_update_proposals)
        )
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_gov_nodrep",
            payment_addr=pool_user_lg.payment,
            action_txid=gov_nodrep_action_txid,
            action_ix=gov_nodrep_action_ix,
            approve_cc=True,
            approve_drep=False,
            approve_spo=None if gov_nodrep_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
        )

        # Vote on update proposals from governance group that will NOT get approved by CC
        if configuration.HAS_CC:
            gov_nocc_update_proposals = list(
                helpers.flatten(random.sample(governance_g_proposals, 3))
            )
            gov_nocc_action_txid, gov_nocc_action_ix, gov_nocc_proposal_names = (
                _create_pparams_action(proposals=gov_nocc_update_proposals)
            )
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_gov_nocc",
                payment_addr=pool_user_lg.payment,
                action_txid=gov_nocc_action_txid,
                action_ix=gov_nocc_action_ix,
                approve_cc=False,
                approve_drep=True,
                approve_spo=None if gov_nocc_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
            )

        # Vote on update proposals from mix of groups that will NOT get approved by DReps
        mix_nodrep_update_proposals = list(
            helpers.flatten(
                [
                    *random.sample(network_g_proposals, 2),
                    *random.sample(economic_g_proposals, 2),
                    *random.sample(technical_g_proposals, 2),
                    *random.sample(governance_g_proposals, 2),
                ]
            )
        )
        mix_nodrep_action_txid, mix_nodrep_action_ix, mix_nodrep_proposal_names = (
            _create_pparams_action(proposals=mix_nodrep_update_proposals)
        )
        conway_common.cast_vote(
            cluster_obj=cluster,
            governance_data=governance_data,
            name_template=f"{temp_template}_mix_nodrep",
            payment_addr=pool_user_lg.payment,
            action_txid=mix_nodrep_action_txid,
            action_ix=mix_nodrep_action_ix,
            approve_cc=True,
            approve_drep=False,
            approve_spo=None if mix_nodrep_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
        )

        # Vote on update proposals from mix of groups that will NOT get approved by CC
        if configuration.HAS_CC:
            mix_nocc_update_proposals = list(
                helpers.flatten(
                    [
                        *random.sample(network_g_proposals, 2),
                        *random.sample(economic_g_proposals, 2),
                        *random.sample(technical_g_proposals, 2),
                        *random.sample(governance_g_proposals, 2),
                    ]
                )
            )
            mix_nocc_action_txid, mix_nocc_action_ix, mix_nocc_proposal_names = (
                _create_pparams_action(proposals=mix_nocc_update_proposals)
            )
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_mix_nocc",
                payment_addr=pool_user_lg.payment,
                action_txid=mix_nocc_action_txid,
                action_ix=mix_nocc_action_ix,
                approve_cc=False,
                approve_drep=True,
                approve_spo=None if mix_nocc_proposal_names.isdisjoint(SECURITY_PPARAMS) else True,
            )

        def _check_state(state: dict):
            pparams = state["curPParams"]
            clusterlib_utils.check_updated_params(
                update_proposals=fin_update_proposals, protocol_params=pparams
            )

        # Check ratification
        req_cip68.start(url=helpers.get_vcs_link())
        _cur_epoch = cluster.g_query.get_epoch()
        if _cur_epoch == fin_approve_epoch:
            _cur_epoch = cluster.wait_for_new_epoch(padding_seconds=5)

        if _cur_epoch == fin_approve_epoch + 1:
            rat_gov_state = cluster.g_conway_governance.query.gov_state()
            conway_common.save_gov_state(
                gov_state=rat_gov_state, name_template=f"{temp_template}_rat_{_cur_epoch}"
            )

            rat_action = governance_utils.lookup_ratified_actions(
                gov_state=rat_gov_state, action_txid=fin_action_txid
            )
            assert rat_action, "Action not found in ratified actions"

            # Disapprove ratified action, the voting shouldn't have any effect
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_after_ratification",
                payment_addr=pool_user_lg.payment,
                action_txid=fin_action_txid,
                action_ix=fin_action_ix,
                approve_cc=False,
                approve_drep=False,
            )

            next_rat_state = rat_gov_state["nextRatifyState"]
            _check_state(next_rat_state["nextEnactState"])
            assert not next_rat_state["ratificationDelayed"], "Ratification is delayed unexpectedly"

            # Wait for enactment
            _cur_epoch = cluster.wait_for_new_epoch(padding_seconds=5)

        # Check enactment
        assert _cur_epoch == fin_approve_epoch + 2, f"Unexpected epoch {_cur_epoch}"
        enact_gov_state = cluster.g_conway_governance.query.gov_state()
        conway_common.save_gov_state(
            gov_state=enact_gov_state, name_template=f"{temp_template}_enact_{_cur_epoch}"
        )
        _check_state(enact_gov_state["enactState"])
        [
            r.success()
            for r in (
                req_cip37,
                req_cip44,
                req_cip45,
                req_cip46,
                req_cip47,
                req_cip49,
                req_cip50,
                req_cip51,
                req_cip52,
                req_cip60,
                req_cip65,
                req_cip68,
                req_cip74,
            )
        ]
        if configuration.HAS_CC:
            req_cip6.success()
        if is_drep_total_below_threshold:
            req_cip64_03.success()
        if is_spo_total_below_threshold:
            req_cip64_04.success()

        # Try to vote on enacted action
        with pytest.raises(clusterlib.CLIError) as excinfo:
            conway_common.cast_vote(
                cluster_obj=cluster,
                governance_data=governance_data,
                name_template=f"{temp_template}_enacted",
                payment_addr=pool_user_lg.payment,
                action_txid=fin_action_txid,
                action_ix=fin_action_ix,
                approve_cc=False,
                approve_drep=False,
            )
        err_str = str(excinfo.value)
        assert "(GovActionsDoNotExist" in err_str, err_str

        # Check vote view
        if fin_voted_votes.cc:
            governance_utils.check_vote_view(cluster_obj=cluster, vote_data=fin_voted_votes.cc[0])
        governance_utils.check_vote_view(cluster_obj=cluster, vote_data=fin_voted_votes.drep[0])


class TestPParamData:
    """Tests for checking protocol parameters keys and values."""

    @allure.link(helpers.get_vcs_link())
    @pytest.mark.testnets
    @pytest.mark.smoke
    def test_pparam_keys(
        self,
        cluster: clusterlib.ClusterLib,
    ):
        """Test presence of expected protocol parameters keys."""
        common.get_test_id(cluster)

        # Linked user stories
        req_cip75 = requirements.Req(id="CIP075", group=requirements.GroupsKnown.CHANG_US)
        req_cip76 = requirements.Req(id="CIP076", group=requirements.GroupsKnown.CHANG_US)
        req_cip77 = requirements.Req(id="CIP077", group=requirements.GroupsKnown.CHANG_US)
        req_cip78 = requirements.Req(id="CIP078", group=requirements.GroupsKnown.CHANG_US)

        _url = helpers.get_vcs_link()
        [r.start(url=_url) for r in (req_cip75, req_cip76, req_cip77, req_cip78)]

        cur_pparam = cluster.g_conway_governance.query.gov_state()["enactState"]["curPParams"]
        for pparam in [
            *NETWORK_GROUP_PPARAMS,
            *ECONOMIC_GROUP_PPARAMS,
            *TECHNICAL_GROUP_PPARAMS,
            *GOVERNANCE_GROUP_PPARAMS,
        ]:
            assert pparam in cur_pparam, f"Param `{pparam}` not found"

        drep_thresholds = cur_pparam["dRepVotingThresholds"]
        for drep_thresh in GOVERNANCE_GROUP_PPARAMS_DREP_THRESHOLDS:
            assert drep_thresh in drep_thresholds, f"DRep threshold `{drep_thresh}` not found"

        pool_thresholds = cur_pparam["poolVotingThresholds"]
        for pool_thresh in GOVERNANCE_GROUP_PPARAMS_POOL_THRESHOLDS:
            assert pool_thresh in pool_thresholds, f"Pool threshold `{pool_thresh}` not found"

        [r.success() for r in (req_cip75, req_cip76, req_cip77, req_cip78)]

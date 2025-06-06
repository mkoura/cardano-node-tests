import dataclasses
import logging

import pytest
from cardano_clusterlib import clusterlib

from cardano_node_tests.tests import issues
from cardano_node_tests.tests import plutus_common
from cardano_node_tests.utils import clusterlib_utils
from cardano_node_tests.utils import dbsync_utils
from cardano_node_tests.utils import tx_view
from cardano_node_tests.utils.versions import VERSIONS

LOGGER = logging.getLogger(__name__)


# Approx. fee for Tx size
FEE_REDEEM_TXSIZE = 400_000


def _fund_script(
    temp_template: str,
    cluster_obj: clusterlib.ClusterLib,
    payment_addr: clusterlib.AddressRecord,
    dst_addr: clusterlib.AddressRecord,
    plutus_op: plutus_common.PlutusOp,
    amount: int,
    tokens: list[clusterlib_utils.Token] | None = None,  # tokens must already be in `payment_addr`
    tokens_collateral: list[clusterlib_utils.Token]
    | None = None,  # tokens must already be in `payment_addr`
    collateral_fraction_offset: float = 1.0,
    embed_datum: bool = False,
) -> tuple[list[clusterlib.UTXOData], list[clusterlib.UTXOData], clusterlib.TxRawOutput]:
    """Fund a Plutus script and create the locked UTxO and collateral UTxO."""
    assert plutus_op.execution_cost  # for mypy

    stokens = tokens or ()
    ctokens = tokens_collateral or ()

    script_address = cluster_obj.g_address.gen_payment_addr(
        addr_name=temp_template, payment_script_file=plutus_op.script_file
    )

    redeem_cost = plutus_common.compute_cost(
        execution_cost=plutus_op.execution_cost,
        protocol_params=cluster_obj.g_query.get_protocol_params(),
        collateral_fraction_offset=collateral_fraction_offset,
    )

    # Create a Tx output with a datum hash at the script address

    tx_files = clusterlib.TxFiles(
        signing_key_files=[payment_addr.skey_file],
    )

    script_txout = plutus_common.txout_factory(
        address=script_address,
        amount=amount,
        plutus_op=plutus_op,
        embed_datum=embed_datum,
    )

    txouts = [
        script_txout,
        # For collateral
        clusterlib.TxOut(address=dst_addr.address, amount=redeem_cost.collateral),
    ]

    txouts.extend(
        dataclasses.replace(script_txout, amount=token.amount, coin=token.coin) for token in stokens
    )

    txouts.extend(
        clusterlib.TxOut(
            address=dst_addr.address,
            amount=token.amount,
            coin=token.coin,
        )
        for token in ctokens
    )

    tx_raw_output = cluster_obj.g_transaction.send_tx(
        src_address=payment_addr.address,
        tx_name=f"{temp_template}_fund_script",
        txouts=txouts,
        tx_files=tx_files,
        # TODO: workaround for https://github.com/IntersectMBO/cardano-node/issues/1892
        witness_count_add=2,
    )

    txid = cluster_obj.g_transaction.get_txid(tx_body_file=tx_raw_output.out_file)

    script_utxos = cluster_obj.g_query.get_utxo(txin=f"{txid}#0")
    assert script_utxos, "No script UTxO"

    assert clusterlib.calculate_utxos_balance(utxos=script_utxos) == txouts[0].amount, (
        f"Incorrect balance for script address `{script_address}`"
    )

    collateral_utxos = cluster_obj.g_query.get_utxo(txin=f"{txid}#1")
    assert collateral_utxos, "No collateral UTxO"

    assert clusterlib.calculate_utxos_balance(utxos=collateral_utxos) == redeem_cost.collateral, (
        f"Incorrect balance for collateral address `{dst_addr.address}`"
    )

    for token in stokens:
        assert (
            clusterlib.calculate_utxos_balance(utxos=script_utxos, coin=token.coin) == token.amount
        ), f"Incorrect token balance for script address `{script_address}`"

    for token in ctokens:
        assert (
            clusterlib.calculate_utxos_balance(utxos=collateral_utxos, coin=token.coin)
            == token.amount
        ), f"Incorrect token balance for address `{dst_addr.address}`"

    if VERSIONS.transaction_era >= VERSIONS.ALONZO:
        dbsync_utils.check_tx(cluster_obj=cluster_obj, tx_raw_output=tx_raw_output)

    return script_utxos, collateral_utxos, tx_raw_output


def _spend_locked_txin(  # noqa: C901
    temp_template: str,
    cluster_obj: clusterlib.ClusterLib,
    payment_addr: clusterlib.AddressRecord,
    dst_addr: clusterlib.AddressRecord,
    script_utxos: list[clusterlib.UTXOData],
    collateral_utxos: list[clusterlib.UTXOData],
    plutus_op: plutus_common.PlutusOp,
    amount: int,
    fee_txsize: int | None = None,
    deposit_amount: int = 0,
    txins: clusterlib.OptionalUTXOData = (),
    tx_files: clusterlib.TxFiles | None = None,
    invalid_hereafter: int | None = None,
    invalid_before: int | None = None,
    tokens: list[clusterlib_utils.Token] | None = None,
    expect_failure: bool = False,
    script_valid: bool = True,
    submit_tx: bool = True,
) -> tuple[str, clusterlib.TxRawOutput]:
    """Spend the locked UTxO."""
    assert plutus_op.execution_cost

    if fee_txsize is None:
        fee_txsize = FEE_REDEEM_TXSIZE

    tx_files = tx_files or clusterlib.TxFiles()
    spent_tokens = tokens or ()
    spent_tokens_dict = {r.coin: r for r in spent_tokens}
    available_tokens = [
        clusterlib_utils.Token(coin=r.coin, amount=r.amount)
        for r in script_utxos
        if r.coin != clusterlib.DEFAULT_COIN
    ]

    script_amount = clusterlib.calculate_utxos_balance(utxos=script_utxos)

    # Spend all locked funds
    if amount == -1:
        amount = script_amount

    # Change that was calculated manually will be returned to address of the first script.
    # The remaining change that is automatically handled by the `build` command will be returned
    # to `payment_addr`, because it would be inaccessible on script address without proper
    # datum hash (datum hash is not provided for change that is handled by `build` command).
    script_change_rec = script_utxos[0]

    redeem_cost = plutus_common.compute_cost(
        execution_cost=plutus_op.execution_cost,
        protocol_params=cluster_obj.g_query.get_protocol_params(),
    )

    # Spend the "locked" UTxO

    plutus_txins = [
        clusterlib.ScriptTxIn(
            txins=script_utxos,
            script_file=plutus_op.script_file,
            collaterals=collateral_utxos,
            execution_units=(plutus_op.execution_cost.per_time, plutus_op.execution_cost.per_space),
            datum_file=plutus_op.datum_file if plutus_op.datum_file else "",
            datum_cbor_file=plutus_op.datum_cbor_file if plutus_op.datum_cbor_file else "",
            datum_value=plutus_op.datum_value if plutus_op.datum_value else "",
            redeemer_file=plutus_op.redeemer_file if plutus_op.redeemer_file else "",
            redeemer_cbor_file=plutus_op.redeemer_cbor_file if plutus_op.redeemer_cbor_file else "",
            redeemer_value=plutus_op.redeemer_value if plutus_op.redeemer_value else "",
        )
    ]

    tx_files = dataclasses.replace(
        tx_files,
        signing_key_files=list({*tx_files.signing_key_files, dst_addr.skey_file}),
    )
    txouts = [
        clusterlib.TxOut(address=dst_addr.address, amount=amount),
    ]

    lovelace_change_needed = False
    for token in available_tokens:
        spent_amount = 0
        script_token_balance = clusterlib.calculate_utxos_balance(
            utxos=script_utxos, coin=token.coin
        )
        if stoken := spent_tokens_dict.get(token.coin):
            spent_amount = stoken.amount
            txouts.append(
                clusterlib.TxOut(address=dst_addr.address, amount=spent_amount, coin=stoken.coin)
            )
        # Append change
        if script_token_balance > spent_amount:
            lovelace_change_needed = True
            txouts.append(
                clusterlib.TxOut(
                    address=script_change_rec.address,
                    amount=script_token_balance - spent_amount,
                    coin=token.coin,
                    datum_hash=script_change_rec.datum_hash,
                )
            )

    # Add minimum (+ some) required Lovelace to change Tx output
    lovelace_token_change = 0
    if lovelace_change_needed:
        lovelace_token_change = 4_000_000
        txouts.append(
            clusterlib.TxOut(
                address=script_change_rec.address,
                amount=lovelace_token_change,
                coin=clusterlib.DEFAULT_COIN,
                datum_hash=script_change_rec.datum_hash,
            )
        )

    input_lovelace_balance = clusterlib.calculate_utxos_balance(utxos=[*txins]) + script_amount
    funds_needed = amount + redeem_cost.fee + fee_txsize + deposit_amount + lovelace_token_change

    if input_lovelace_balance < funds_needed:
        # Add additional funds to cover fee and Lovelace change for token txouts
        fee_txin = next(
            r
            for r in clusterlib_utils.get_just_lovelace_utxos(
                address_utxos=cluster_obj.g_query.get_utxo(address=payment_addr.address)
            )
            if r.amount >= 100_000_000
        )
        txins = [
            *txins,
            fee_txin,
        ]
        tx_files = dataclasses.replace(
            tx_files,
            signing_key_files=list({*tx_files.signing_key_files, payment_addr.skey_file}),
        )
        input_lovelace_balance = clusterlib.calculate_utxos_balance(utxos=[*txins]) + script_amount

    # Append change
    change_lovelace = input_lovelace_balance - funds_needed
    if change_lovelace > 0:
        txouts.append(
            clusterlib.TxOut(
                address=payment_addr.address,
                amount=change_lovelace,
            )
        )

    tx_raw_output = cluster_obj.g_transaction.build_raw_tx_bare(
        out_file=f"{temp_template}_spend_tx.body",
        txins=txins,
        txouts=txouts,
        tx_files=tx_files,
        fee=redeem_cost.fee + fee_txsize,
        script_txins=plutus_txins,
        invalid_hereafter=invalid_hereafter,
        invalid_before=invalid_before,
        script_valid=script_valid,
    )
    tx_signed = cluster_obj.g_transaction.sign_tx(
        tx_body_file=tx_raw_output.out_file,
        signing_key_files=tx_files.signing_key_files,
        tx_name=f"{temp_template}_spend",
    )

    if not submit_tx:
        return "", tx_raw_output

    dst_init_balance = cluster_obj.g_query.get_address_balance(dst_addr.address)
    script_utxos_lovelace = [u for u in script_utxos if u.coin == clusterlib.DEFAULT_COIN]

    if not script_valid:
        cluster_obj.g_transaction.submit_tx_bare(tx_file=tx_signed)

        cluster_obj.wait_for_new_block(new_blocks=2)
        try:
            cluster_obj.g_transaction.submit_tx_bare(tx_file=tx_signed)
        except clusterlib.CLIError as exc:
            # Check if resubmitting failed because an input UTxO was already spent
            if "(BadInputsUTxO" not in str(exc):
                raise
        else:
            pytest.fail("Transaction was not submitted successfully")

        # Check that the collateral UTxO was spent
        spent_collateral_utxo = cluster_obj.g_query.get_utxo(utxo=collateral_utxos)
        if spent_collateral_utxo:
            issues.consensus_973.finish_test()

        assert (
            cluster_obj.g_query.get_address_balance(dst_addr.address)
            == dst_init_balance - collateral_utxos[0].amount
        ), f"Collateral was NOT spent from `{dst_addr.address}`"

        for u in script_utxos_lovelace:
            assert cluster_obj.g_query.get_utxo(utxo=u, coins=[clusterlib.DEFAULT_COIN]), (
                f"Inputs were unexpectedly spent for `{u.address}`"
            )

        return "", tx_raw_output

    if expect_failure:
        with pytest.raises(clusterlib.CLIError) as excinfo:
            cluster_obj.g_transaction.submit_tx_bare(tx_file=tx_signed)
        err = str(excinfo.value)
        assert cluster_obj.g_query.get_address_balance(dst_addr.address) == dst_init_balance, (
            f"Collateral was spent from `{dst_addr.address}`"
        )

        for u in script_utxos_lovelace:
            assert cluster_obj.g_query.get_utxo(utxo=u, coins=[clusterlib.DEFAULT_COIN]), (
                f"Inputs were unexpectedly spent for `{u.address}`"
            )

        return err, tx_raw_output

    cluster_obj.g_transaction.submit_tx(
        tx_file=tx_signed, txins=[t.txins[0] for t in tx_raw_output.script_txins if t.txins]
    )

    assert cluster_obj.g_query.get_address_balance(dst_addr.address) == dst_init_balance + amount, (
        f"Incorrect balance for destination address `{dst_addr.address}`"
    )

    for u in script_utxos_lovelace:
        assert not cluster_obj.g_query.get_utxo(utxo=u, coins=[clusterlib.DEFAULT_COIN]), (
            f"Inputs were NOT spent for `{u.address}`"
        )

    for token in spent_tokens:
        script_utxos_token = [u for u in script_utxos if u.coin == token.coin]
        for u in script_utxos_token:
            assert not cluster_obj.g_query.get_utxo(utxo=u, coins=[token.coin]), (
                f"Token inputs were NOT spent for `{u.address}`"
            )

    # Check tx view
    tx_view.check_tx_view(cluster_obj=cluster_obj, tx_raw_output=tx_raw_output)

    dbsync_utils.check_tx(cluster_obj=cluster_obj, tx_raw_output=tx_raw_output)

    return "", tx_raw_output

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @notice Minimal ERC20 Interface
interface IERC20 {
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address recipient, uint256 amount) external returns (bool);
    function allowance(address owner, address spender) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
    function transferFrom(address sender, address recipient, uint256 amount) external returns (bool);
}

/// @notice Aave V3 Flash Loan Simple Receiver Interface
interface IFlashLoanSimpleReceiver {
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool);
}

/// @notice Aave V3 Pool Interface for requesting Flash Loans
interface IPool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

/// @title Universal Multi-DEX Flash Arbitrage Receiver (v3.0)
/// @notice Executes zero-capital atomic cross-DEX arbitrage across Uniswap V3, Aerodrome, Camelot, PancakeSwap, and SushiSwap
contract UniversalFlashArbitrageReceiver is IFlashLoanSimpleReceiver {
    address public immutable owner;
    IPool public immutable aavePool;

    error Unauthorized();
    error InsufficientArbitrageProfit(uint256 obtained, uint256 required);
    error SwapExecutionFailed(uint8 legIndex, bytes reason);

    event CrossDexArbitrageExecuted(
        address indexed asset,
        uint256 borrowedAmount,
        uint256 premiumPaid,
        uint256 netProfit,
        address router1,
        address router2
    );

    struct SwapLeg {
        address router;       // Address of DEX Router (Uniswap, Aerodrome, Camelot, etc.)
        address tokenIn;      // Input token to swap
        address tokenOut;     // Output token to receive
        uint256 amountIn;     // Input amount (0 means use full balance of tokenIn)
        bytes swapData;       // Encoded calldata to call on router
    }

    struct CrossDexParams {
        SwapLeg leg1;
        SwapLeg leg2;
        uint256 minProfit;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    constructor(address _aavePool) {
        owner = msg.sender;
        aavePool = IPool(_aavePool);
    }

    /// @notice Request flash loan from Aave V3
    function requestFlashLoan(
        address asset,
        uint256 amount,
        bytes calldata params
    ) external onlyOwner {
        aavePool.flashLoanSimple(address(this), asset, amount, params, 0);
    }

    /// @notice Callback called by Aave V3 pool after transferring flash loaned funds
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {
        require(msg.sender == address(aavePool), "Caller must be Aave Pool");
        require(initiator == address(this), "Initiator must be this contract");

        uint256 amountToRepay = amount + premium;
        CrossDexParams memory p = abi.decode(params, (CrossDexParams));

        // -------------------------------------------------------------
        // LEG 1: Swap borrowed asset -> intermediate token on Router 1
        // -------------------------------------------------------------
        uint256 leg1AmountIn = p.leg1.amountIn > 0 ? p.leg1.amountIn : amount;
        IERC20(p.leg1.tokenIn).approve(p.leg1.router, leg1AmountIn);

        (bool success1, bytes memory returnData1) = p.leg1.router.call(p.leg1.swapData);
        if (!success1) {
            revert SwapExecutionFailed(1, returnData1);
        }

        // -------------------------------------------------------------
        // LEG 2: Swap intermediate token -> original asset on Router 2
        // -------------------------------------------------------------
        uint256 intermBalance = IERC20(p.leg2.tokenIn).balanceOf(address(this));
        uint256 leg2AmountIn = p.leg2.amountIn > 0 ? p.leg2.amountIn : intermBalance;
        IERC20(p.leg2.tokenIn).approve(p.leg2.router, leg2AmountIn);

        (bool success2, bytes memory returnData2) = p.leg2.router.call(p.leg2.swapData);
        if (!success2) {
            revert SwapExecutionFailed(2, returnData2);
        }

        // -------------------------------------------------------------
        // PROFIT & REPAYMENT VALIDATION
        // -------------------------------------------------------------
        uint256 finalBalance = IERC20(asset).balanceOf(address(this));
        uint256 requiredTotal = amountToRepay + p.minProfit;

        if (finalBalance < requiredTotal) {
            revert InsufficientArbitrageProfit(finalBalance, requiredTotal);
        }

        uint256 netProfit = finalBalance - amountToRepay;

        // Approve Aave V3 for repayment
        IERC20(asset).approve(address(aavePool), amountToRepay);

        // Transfer profit to Sovereign Owner
        if (netProfit > 0) {
            IERC20(asset).transfer(owner, netProfit);
        }

        emit CrossDexArbitrageExecuted(
            asset,
            amount,
            premium,
            netProfit,
            p.leg1.router,
            p.leg2.router
        );

        return true;
    }

    /// @notice Rescue any token from contract
    function withdrawToken(address token) external onlyOwner {
        uint256 bal = IERC20(token).balanceOf(address(this));
        if (bal > 0) {
            IERC20(token).transfer(owner, bal);
        }
    }

    /// @notice Rescue ETH from contract
    function withdrawETH() external onlyOwner {
        uint256 bal = address(this).balance;
        if (bal > 0) {
            (bool s, ) = payable(owner).call{value: bal}("");
            require(s, "ETH transfer failed");
        }
    }

    receive() external payable {}
}

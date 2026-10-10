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

/// @notice Minimal Uniswap V3 Swap Router Interface
interface ISwapRouter {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(ExactInputSingleParams calldata params) external payable returns (uint256 amountOut);
}

/// @title Sovereign Flash Arbitrage Receiver
/// @notice Executes atomic arbitrage using zero-capital Aave V3 Flash Loans across DEXs
contract FlashArbitrageReceiver is IFlashLoanSimpleReceiver {
    address public immutable owner;
    IPool public immutable aavePool;
    ISwapRouter public immutable swapRouter;

    error Unauthorized();
    error InsufficientArbitrageProfit(uint256 obtained, uint256 required);

    event ArbitrageExecuted(
        address indexed asset,
        uint256 borrowedAmount,
        uint256 premiumPaid,
        uint256 netProfit
    );

    struct ArbParams {
        address intermediateToken;
        uint24 poolFee1;
        uint24 poolFee2;
        uint256 minProfit;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    constructor(address _aavePool, address _swapRouter) {
        owner = msg.sender;
        aavePool = IPool(_aavePool);
        swapRouter = ISwapRouter(_swapRouter);
    }

    function requestFlashLoan(address asset, uint256 amount, bytes calldata params) external onlyOwner {
        aavePool.flashLoanSimple(address(this), asset, amount, params, 0);
    }

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
        ArbParams memory p = abi.decode(params, (ArbParams));

        // Swap 1: asset -> intermediateToken
        IERC20(asset).approve(address(swapRouter), amount);
        uint256 intermediateAmount = swapRouter.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn: asset,
                tokenOut: p.intermediateToken,
                fee: p.poolFee1,
                recipient: address(this),
                deadline: block.timestamp,
                amountIn: amount,
                amountOutMinimum: 0,
                sqrtPriceLimitX96: 0
            })
        );

        // Swap 2: intermediateToken -> asset
        IERC20(p.intermediateToken).approve(address(swapRouter), intermediateAmount);
        uint256 finalAssetAmount = swapRouter.exactInputSingle(
            ISwapRouter.ExactInputSingleParams({
                tokenIn: p.intermediateToken,
                tokenOut: asset,
                fee: p.poolFee2,
                recipient: address(this),
                deadline: block.timestamp,
                amountIn: intermediateAmount,
                amountOutMinimum: amountToRepay + p.minProfit,
                sqrtPriceLimitX96: 0
            })
        );

        if (finalAssetAmount < amountToRepay + p.minProfit) {
            revert InsufficientArbitrageProfit(finalAssetAmount, amountToRepay + p.minProfit);
        }

        uint256 netProfit = finalAssetAmount - amountToRepay;

        // Approve repayment
        IERC20(asset).approve(address(aavePool), amountToRepay);

        // Transfer profit
        if (netProfit > 0) {
            IERC20(asset).transfer(owner, netProfit);
        }

        emit ArbitrageExecuted(asset, amount, premium, netProfit);
        return true;
    }

    function withdrawToken(address token) external onlyOwner {
        uint256 bal = IERC20(token).balanceOf(address(this));
        IERC20(token).transfer(owner, bal);
    }
}
